"""World ID Agent Pass (World IdP, https://auth.world.org): OIDC login and human checkpoints for agent actions.

Two uses of one OIDC client (authorization code + PKCE S256, client_secret_basic, ID token RS256):
- login: the hosted MCP's /login sends the person to World IdP; the callback validates the ID token here, in the
  backend, and the person becomes keccak("worldidp|" + iss + "|" + sub) (sub is pairwise, so stable per person).
- checkpoint: before Lore signs a stake, purchase, vote or claim for an agent, the person must complete a FRESH
  World ID authentication (max_age=0, prompt=login). The approval is bound to that one prepared action, to the same
  person, is single-use and expires. Denied, cancelled, mismatched or expired attempts never release the action.

Nothing from the browser is trusted: state, nonce and the PKCE verifier live in the gateway's database, the code is
redeemed server-side with the client secret, and the ID token's signature, iss, aud, exp, nonce, acr and auth_time
are all checked before anything is authorized.
"""

import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode

import httpx
import jwt
from eth_utils import keccak

ATTEMPT_TTL = 600  # seconds a login/approval attempt stays open
CLOCK_SKEW = 60
ACCEPTED_ACR = ("https://world.org/oidc/acr/orb", "https://world.org/oidc/acr/orb-face")  # advertised by discovery


class WorldIdPError(Exception):
    """The attempt did not produce a valid, fresh, matching World ID authentication."""


def person_of(iss: str, sub: str) -> str:
    """Lore's person id for a World IdP subject: same 0x-bytes32 shape as PersonRegistry uses."""
    return "0x" + keccak(f"worldidp|{iss}|{sub}".encode()).hex()


class WorldIdP:
    def __init__(self, issuer: str, client_id: str, client_secret: str, redirect_uri: str,
                 http: httpx.Client | None = None, now=time.time, jwks_client=None):
        self.issuer, self.client_id, self.client_secret = issuer.rstrip("/"), client_id, client_secret
        self.redirect_uri, self.now = redirect_uri, now
        self.http = http or httpx.Client(timeout=30)
        self._meta = None
        self._jwks = jwks_client

    # --- discovery ---
    def meta(self) -> dict:
        if self._meta is None:
            r = self.http.get(f"{self.issuer}/.well-known/openid-configuration")
            r.raise_for_status()
            meta = r.json()
            if meta.get("issuer") != self.issuer:
                raise WorldIdPError("discovery issuer does not match the configured issuer")
            self._meta = meta
        return self._meta

    def jwks(self):
        if self._jwks is None:
            self._jwks = jwt.PyJWKClient(self.meta()["jwks_uri"], cache_keys=True)
        return self._jwks

    # --- one attempt: begin (redirect) and finish (callback) ---
    def authorize_url(self, *, fresh: bool) -> tuple[str, dict]:
        """Returns (URL to send the browser to, attempt secrets to store server-side)."""
        state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        params = {
            "response_type": "code", "client_id": self.client_id, "redirect_uri": self.redirect_uri,
            "scope": "openid", "state": state, "nonce": nonce,
            "code_challenge": challenge, "code_challenge_method": "S256",
            "claims": json.dumps({"id_token": {"acr": {"essential": True, "values": list(ACCEPTED_ACR)}}},
                                 separators=(",", ":")),
        }
        if fresh:  # a human checkpoint: always a new authentication, never a remembered session
            params.update(max_age="0", prompt="login")
        url = f"{self.meta()['authorization_endpoint']}?{urlencode(params)}"
        return url, {"state": state, "nonce": nonce, "verifier": verifier, "created": int(self.now())}

    def finish(self, attempt: dict, query: dict, *, fresh: bool) -> dict:
        """Validate the callback for a stored attempt. Returns the verified ID token claims or raises."""
        if int(self.now()) - attempt["created"] > ATTEMPT_TTL:
            raise WorldIdPError("expired: the World ID check took too long")
        if query.get("error"):  # the person denied/cancelled, or World IdP refused (e.g. unmet_authentication_requirements)
            raise WorldIdPError(f"denied: {query['error']}")
        if query.get("iss") and query["iss"] != self.issuer:  # RFC 9207 mix-up defence (advertised by discovery)
            raise WorldIdPError("callback came from the wrong issuer")
        code = query.get("code")
        if not code:
            raise WorldIdPError("no authorization code in the callback")
        r = self.http.post(self.meta()["token_endpoint"], auth=(self.client_id, self.client_secret), data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri,
            "code_verifier": attempt["verifier"]})
        if r.status_code != 200:
            raise WorldIdPError(f"token exchange failed: {r.status_code} {r.text[:200]}")
        id_token = r.json().get("id_token")
        if not id_token:
            raise WorldIdPError("no ID token returned")
        return self.validate(id_token, attempt, fresh=fresh)

    def validate(self, id_token: str, attempt: dict, *, fresh: bool) -> dict:
        try:
            key = self.jwks().get_signing_key_from_jwt(id_token).key
            claims = jwt.decode(id_token, key, algorithms=["RS256"], audience=self.client_id, issuer=self.issuer,
                                leeway=CLOCK_SKEW, options={"require": ["iss", "sub", "aud", "exp", "iat", "nonce"]})
        except jwt.PyJWTError as e:
            raise WorldIdPError(f"invalid ID token: {e}") from e
        if claims.get("nonce") != attempt["nonce"]:
            raise WorldIdPError("ID token nonce does not match this attempt")
        if claims.get("acr") not in ACCEPTED_ACR:
            raise WorldIdPError(f"credential class not accepted: {claims.get('acr')!r}")
        if fresh:  # max_age=0: the authentication must have happened during THIS attempt
            auth_time = claims.get("auth_time")
            if not isinstance(auth_time, (int, float)):
                raise WorldIdPError("no auth_time in a fresh check")
            if auth_time < attempt["created"] - CLOCK_SKEW or auth_time > self.now() + CLOCK_SKEW:
                raise WorldIdPError("not a fresh authentication for this approval")
        return claims
