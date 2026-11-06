"""OAuth 2.1 for the hosted MCP, with World ID as the only way to log in.

The MCP client (Claude Code, Cursor, ...) registers itself, then sends the user to /authorize. We redirect
to our /login page, where the user proves their World ID in World App. The proof's signal is the pending
login's own id, so it can't be replayed into another login. Every token's subject is the person (the
World ID nullifier for Lore's action), which is the same id PersonRegistry uses on-chain.

State lives in the gateway's sqlite database. Codes and pending logins are single-use and short-lived;
refresh tokens rotate on use.
"""

import json
import re
import secrets
import time
from urllib.parse import urlsplit

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from gateway.db import connect

SCOPES = ["lore"]
PENDING_TTL, CODE_TTL, ACCESS_TTL, REFRESH_TTL = 1800, 300, 3600, 30 * 24 * 3600  # login: 30 min to finish World ID
UNUSED_CLIENT_TTL = 24 * 3600  # registration is open: forget clients that never completed a login
MAX_PENDING = 10_000           # open /authorize can't grow the database without bound
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
BLOCKED_SCHEMES = {"javascript", "data", "vbscript", "file", "about", "blob", "filesystem", "view-source"}


def safe_redirect(uri: str) -> bool:
    """https anywhere; http only to this machine (RFC 8252 loopback); or an app's own scheme (cursor://, ...).

    Never javascript:, data: and the like: the login page navigates to the redirect in Lore's own origin.
    """
    parts = urlsplit(str(uri))
    scheme = parts.scheme.lower()
    if scheme == "https":
        return bool(parts.hostname)
    if scheme == "http":
        return parts.hostname in LOOPBACK
    return bool(re.fullmatch(r"[a-z][a-z0-9+.-]*", scheme)) and scheme not in BLOCKED_SCHEMES


def is_local(uri: str) -> bool:
    parts = urlsplit(str(uri))
    return parts.scheme.lower() == "http" and parts.hostname in LOOPBACK


class WorldIDOAuth:
    def __init__(self, db_path: str, public_url: str, now=time.time):
        self.db_path, self.public_url, self.now = db_path, public_url.rstrip("/"), now

    def _db(self):
        return connect(self.db_path)

    # --- clients (dynamic registration) ---
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with self._db() as db:
            row = db.execute("SELECT info FROM oauth_clients WHERE client_id=?", (client_id,)).fetchone()
        return OAuthClientInformationFull.model_validate_json(row[0]) if row else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        bad = [str(u) for u in (client_info.redirect_uris or []) if not safe_redirect(str(u))]
        if bad:
            raise RegistrationError("invalid_redirect_uri",
                                    "redirect URIs must be https, http to localhost, or an app scheme")
        now = int(self.now())
        with self._db() as db:
            db.execute("DELETE FROM oauth_clients WHERE created < ? AND client_id NOT IN"
                       " (SELECT client_id FROM oauth_tokens) AND client_id NOT IN (SELECT client_id FROM oauth_pending)",
                       (now - UNUSED_CLIENT_TTL,))
            db.execute("INSERT OR REPLACE INTO oauth_clients VALUES (?, ?, ?)",
                       (client_info.client_id, client_info.model_dump_json(), now))

    # --- authorize: hand the user to our World ID page ---
    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        pending = secrets.token_hex(16)  # lowercase hex: it is also the World ID signal
        now = int(self.now())
        with self._db() as db:
            # Housekeeping on the open path: expired logins, codes and tokens go.
            db.execute("DELETE FROM oauth_pending WHERE expires <= ?", (now,))
            db.execute("DELETE FROM oauth_tokens WHERE expires <= ?", (now,))
            db.execute("DELETE FROM oauth_codes WHERE json_extract(data, '$.expires_at') <= ?", (now,))
            if db.execute("SELECT COUNT(*) FROM oauth_pending").fetchone()[0] >= MAX_PENDING:
                raise AuthorizeError("temporarily_unavailable", "too many logins in progress; try again shortly")
            db.execute("INSERT INTO oauth_pending VALUES (?, ?, ?, ?)",
                       (pending, client.client_id, params.model_dump_json(), int(self.now()) + PENDING_TTL))
        return f"{self.public_url}/login?pending={pending}"

    def pending(self, pending: str) -> dict | None:
        """The pending login with what the consent screen shows, if it exists and hasn't expired."""
        with self._db() as db:
            row = db.execute("SELECT p.*, c.info FROM oauth_pending p JOIN oauth_clients c ON c.client_id=p.client_id"
                             " WHERE p.id=? AND p.expires>?", (pending, int(self.now()))).fetchone()
        if not row:
            return None
        client = OAuthClientInformationFull.model_validate_json(row["info"])
        redirect = str(AuthorizationParams.model_validate_json(row["params"]).redirect_uri)
        return {"client_id": row["client_id"], "client_name": client.client_name or row["client_id"],
                "redirect": redirect, "redirect_host": urlsplit(redirect).netloc or urlsplit(redirect).scheme + ":",
                "local": is_local(redirect)}

    def complete_login(self, pending: str, person: str) -> str | None:
        """The user approved and proved `person` for this pending login: issue a code and return the client's
        redirect URL, or None if the login is gone (expired or already used)."""
        with self._db() as db:
            row = db.execute("DELETE FROM oauth_pending WHERE id=? AND expires>? RETURNING *",
                             (pending, int(self.now()))).fetchone()
            if not row:
                return None
            params = AuthorizationParams.model_validate_json(row["params"])
            if not safe_redirect(str(params.redirect_uri)):  # checked at registration too; never navigate to it
                return None
            code = AuthorizationCode(
                code=secrets.token_urlsafe(32), scopes=params.scopes or SCOPES, expires_at=self.now() + CODE_TTL,
                client_id=row["client_id"], code_challenge=params.code_challenge, redirect_uri=params.redirect_uri,
                redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly, resource=params.resource,
                subject=person,
            )
            db.execute("INSERT INTO oauth_codes VALUES (?, ?)", (code.code, code.model_dump_json()))
        return construct_redirect_uri(str(params.redirect_uri), code=code.code, state=params.state)

    # --- codes and tokens ---
    async def load_authorization_code(self, client, authorization_code: str) -> AuthorizationCode | None:
        with self._db() as db:
            row = db.execute("SELECT data FROM oauth_codes WHERE code=?", (authorization_code,)).fetchone()
        code = AuthorizationCode.model_validate_json(row[0]) if row else None
        if code and (code.client_id != client.client_id or code.expires_at < self.now()):
            return None
        return code

    async def exchange_authorization_code(self, client, authorization_code: AuthorizationCode) -> OAuthToken:
        with self._db() as db:
            if db.execute("DELETE FROM oauth_codes WHERE code=?", (authorization_code.code,)).rowcount != 1:
                raise TokenError("invalid_grant", "code already used")
            return self._issue(db, client.client_id, authorization_code.subject, authorization_code.scopes,
                               authorization_code.resource)

    async def load_refresh_token(self, client, refresh_token: str) -> RefreshToken | None:
        row = self._token(refresh_token, "refresh")
        if not row or row["client_id"] != client.client_id:
            return None
        return RefreshToken(token=refresh_token, client_id=row["client_id"], scopes=json.loads(row["scopes"]),
                            expires_at=row["expires"], resource=row["resource"], subject=row["person"])

    async def exchange_refresh_token(self, client, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        with self._db() as db:
            db.execute("DELETE FROM oauth_tokens WHERE token=?", (refresh_token.token,))  # rotate
            return self._issue(db, client.client_id, refresh_token.subject, scopes or refresh_token.scopes,
                               refresh_token.resource)

    async def load_access_token(self, token: str) -> AccessToken | None:
        row = self._token(token, "access")
        if not row:
            return None
        return AccessToken(token=token, client_id=row["client_id"], scopes=json.loads(row["scopes"]),
                           expires_at=row["expires"], resource=row["resource"], subject=row["person"])

    async def revoke_token(self, token) -> None:
        with self._db() as db:  # revoke the whole login: every token of this client for this person
            row = db.execute("SELECT client_id, person FROM oauth_tokens WHERE token=?", (token.token,)).fetchone()
            if row:
                db.execute("DELETE FROM oauth_tokens WHERE client_id=? AND person=?", (row[0], row[1]))

    def _token(self, token: str, kind: str):
        with self._db() as db:
            return db.execute("SELECT * FROM oauth_tokens WHERE token=? AND kind=? AND expires>?",
                              (token, kind, int(self.now()))).fetchone()

    def _issue(self, db, client_id: str, person: str, scopes: list[str], resource: str | None) -> OAuthToken:
        access, refresh, now = secrets.token_urlsafe(32), secrets.token_urlsafe(32), int(self.now())
        rows = [(access, "access", client_id, person, json.dumps(scopes), now + ACCESS_TTL, resource),
                (refresh, "refresh", client_id, person, json.dumps(scopes), now + REFRESH_TTL, resource)]
        db.executemany("INSERT INTO oauth_tokens VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        return OAuthToken(access_token=access, token_type="Bearer", expires_in=ACCESS_TTL,
                          refresh_token=refresh, scope=" ".join(scopes))
