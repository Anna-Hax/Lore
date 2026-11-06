"""SIWE-style sign-in: sign a one-time message, get a short-lived bearer token."""

import secrets
import time

from eth_account import Account
from eth_account.messages import encode_defunct

NONCE_TTL, TOKEN_TTL = 300, 3600


def new_message(db, address: str) -> str:
    address = address.lower()
    msg = f"Sign in to Lore\nAddress: {address}\nNonce: {secrets.token_hex(16)}"
    # Keyed by message, so asking for a new nonce never cancels someone's sign-in in progress.
    db.execute("DELETE FROM nonces WHERE expires < ?", (int(time.time()),))
    db.execute("INSERT INTO nonces VALUES (?, ?, ?)", (msg, address, int(time.time()) + NONCE_TTL))
    return msg


def verify(db, address: str, message: str, signature: str) -> str | None:
    """Return a bearer token if `signature` signs a pending `message` issued to `address`."""
    address = address.lower()
    row = db.execute(
        "DELETE FROM nonces WHERE message=? AND address=? RETURNING message, expires", (message, address)
    ).fetchone()
    if not row or row["expires"] < time.time():
        return None
    try:
        signer = Account.recover_message(encode_defunct(text=row["message"]), signature=signature)
    except Exception:
        return None
    if signer.lower() != address:
        return None
    token = secrets.token_urlsafe(32)
    db.execute("INSERT INTO tokens VALUES (?, ?, ?)", (token, address, int(time.time()) + TOKEN_TTL))
    return token


def address_for(db, token: str) -> str | None:
    row = db.execute("SELECT address FROM tokens WHERE token=? AND expires>?", (token, time.time())).fetchone()
    return row["address"] if row else None


def is_login_message(message: str, address: str) -> bool:
    """Clients check this before signing, so a dishonest gateway can't get them to sign anything else."""
    import re

    return re.fullmatch(rf"Sign in to Lore\nAddress: {address.lower()}\nNonce: [0-9a-f]{{32}}", message) is not None
