"""World ID 4.0 RP signing in Python: a port of signRequest from @worldcoin/idkit-server 1.2.0.

World ships it only for JS and Go (spike W1). test_world_id.py holds this to the SDK's own outputs byte for byte.
"""

import secrets
import time

from eth_keys import keys
from eth_utils import keccak

DEFAULT_TTL = 300
MESSAGE_VERSION = 1


def hash_to_field(data: bytes) -> bytes:
    return (int.from_bytes(keccak(data), "big") >> 8).to_bytes(32, "big")


def hash_signal(signal: str) -> str:
    """IDKit's hashSignal. A string that is 0x-hex is hashed as those bytes, not as text."""
    body = signal[2:]
    if signal.startswith("0x") and body and len(body) % 2 == 0 and all(c in "0123456789abcdefABCDEF" for c in body):
        return "0x" + hash_to_field(bytes.fromhex(body)).hex()
    return "0x" + hash_to_field(signal.encode()).hex()


def rp_message(nonce: bytes, created_at: int, expires_at: int, action: str | None = None) -> bytes:
    tail = b"" if action is None else hash_to_field(action.encode())
    return bytes([MESSAGE_VERSION]) + nonce + created_at.to_bytes(8, "big") + expires_at.to_bytes(8, "big") + tail


def rp_signature(signing_key: str, message: bytes) -> str:
    digest = keccak(b"\x19Ethereum Signed Message:\n" + str(len(message)).encode() + message)
    sig = keys.PrivateKey(bytes.fromhex(signing_key.removeprefix("0x"))).sign_msg_hash(digest)
    return "0x" + (sig.r.to_bytes(32, "big") + sig.s.to_bytes(32, "big") + bytes([sig.v + 27])).hex()


def rp_context(rp_id: str, signing_key: str, action: str, ttl: int = DEFAULT_TTL) -> dict:
    """What IDKit.request() takes as `rp_context`."""
    nonce = hash_to_field(secrets.token_bytes(32))
    created_at = int(time.time())
    expires_at = created_at + ttl
    return {"rp_id": rp_id, "nonce": "0x" + nonce.hex(), "created_at": created_at, "expires_at": expires_at,
            "signature": rp_signature(signing_key, rp_message(nonce, created_at, expires_at, action))}
