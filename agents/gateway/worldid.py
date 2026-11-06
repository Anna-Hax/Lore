"""World ID 4.0 for the gateway: who the user is (login), and later which wallets are theirs.

World ID can't be verified on 0G (no World ID contracts there), so the gateway verifies proofs with World's
API. The person id is the proof's nullifier for Lore's one action, the same for one human whatever they
prove it for, so login and the on-chain PersonRegistry agree on who someone is. Every proof is bound to a
signal: a login request's own id for sign-in (so a proof can't be replayed into another login), or a
wallet address when linking a wallet (next step, with signing).

Config (Developer Portal): WORLD_APP_ID, WORLD_RP_ID, WORLD_RP_SIGNING_KEY, WORLD_ACTION (default
"lore-person"), WORLD_IDKIT_MODULE (a pinned ESM URL of @worldcoin/idkit-core that the /login page loads).
The action must allow unlimited verifications per person, since each agent verifies.
"""

import secrets
import time

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak

VERIFY_URL = "https://developer.world.org/api/v4/verify/{rp_id}"
# The decided policy: Orb or device. Order = preference when one proof carries both.
# ponytail: if spike W3 finds the nullifier differs across credential types, keep only one here, or one
# human could register two agents as two people.
ALLOWED_CREDENTIALS = ("orb", "device")


IDKIT_MODULE = "https://cdn.jsdelivr.net/npm/@worldcoin/idkit-core@4.6.0/+esm"  # pinned; no WASM, loads from a CDN
RP_SIGNATURE_VERSION = 1
RP_SIGNATURE_TTL = 300  # seconds, IDKit's default


def hash_to_field(data: bytes) -> bytes:
    """IDKit's hashToField: keccak256(data) >> 8, as 32 big-endian bytes."""
    return (int.from_bytes(keccak(data), "big") >> 8).to_bytes(32, "big")


def rp_signature_message(nonce: bytes, created_at: int, expires_at: int, action: str | None = None) -> bytes:
    """@worldcoin/idkit-server computeRpSignatureMessage (v1.2.0):
    version(1) || nonce(32) || created_at u64 BE (8) || expires_at u64 BE (8) || hashToField(action)? (32)."""
    if len(nonce) != 32:
        raise ValueError("nonce must be 32 bytes")
    msg = bytes([RP_SIGNATURE_VERSION]) + nonce + created_at.to_bytes(8, "big") + expires_at.to_bytes(8, "big")
    return msg + (hash_to_field(action.encode()) if action is not None else b"")


def sign_request(signing_key: str, action: str | None = None, ttl: int = RP_SIGNATURE_TTL,
                 now=time.time, entropy=lambda: secrets.token_bytes(32)) -> dict:
    """Python port of @worldcoin/idkit-server signRequest: EIP-191 personal_sign of the RP message.

    Returns {sig, nonce, created_at, expires_at}; sig is r || s || v with v = 27/28, like the JS version."""
    nonce = hash_to_field(entropy())
    created = int(now())
    expires = created + ttl
    signed = Account.sign_message(encode_defunct(primitive=rp_signature_message(nonce, created, expires, action)),
                                  private_key=signing_key)
    return {"sig": "0x" + bytes(signed.signature).hex(), "nonce": "0x" + nonce.hex(),
            "created_at": created, "expires_at": expires}


class WorldIDError(Exception):
    """The proof is not a valid World ID proof for this agent and action."""


def to_bytes32_hex(value) -> str:
    """World returns field elements as 0x-hex (docs) but may send decimal; accept both, reject overflow."""
    s = str(value).strip()
    n = int(s, 16) if s.lower().startswith("0x") else int(s)
    if not 0 < n < 2**256:
        raise WorldIDError("nullifier out of range")
    return "0x" + format(n, "064x")


def signal_hash(signal: str) -> str:
    # ponytail: IDKit's hashToField (keccak256(utf8 signal) >> 8), as in World ID 3.0. Confirm for 4.0 in spike W3.
    return "0x" + format(int.from_bytes(keccak(text=signal), "big") >> 8, "064x")


class WorldID:
    def __init__(self, app_id: str, rp_id: str, action: str, signing_key: str | None = None,
                 idkit_module: str | None = None, http: httpx.Client | None = None,
                 allowed: tuple[str, ...] = ALLOWED_CREDENTIALS):
        self.app_id, self.rp_id, self.action, self.signing_key = app_id, rp_id, action, signing_key
        self.idkit_module, self.allowed = idkit_module or IDKIT_MODULE, allowed
        self.http = http or httpx.Client(timeout=30)

    def request(self, signal: str) -> dict:
        """What the user's browser needs to ask World App for a proof bound to `signal`."""
        return {"app_id": self.app_id, "rp_id": self.rp_id, "action": self.action, "signal": signal,
                "rp_context": self.rp_context(), "idkit_module": self.idkit_module}

    def rp_context(self) -> dict:
        """The signed RP context IDKit.request() needs (spike W1: signRequest ported from idkit-server 1.2.0)."""
        if not self.signing_key:
            raise NotImplementedError("WORLD_RP_SIGNING_KEY is not set")
        r = sign_request(self.signing_key, self.action)
        return {"rp_id": self.rp_id, "nonce": r["nonce"], "created_at": r["created_at"],
                "expires_at": r["expires_at"], "signature": r["sig"]}

    def verify(self, result: dict, signal: str) -> str:
        """Check an IDKit result is for our action, an allowed credential and bound to exactly `signal`; verify
        it with World; return the person (the nullifier of the allowed credential World confirmed)."""
        responses = result.get("responses") or []
        if result.get("action") != self.action or not responses:
            raise WorldIDError("proof is for a different action")
        expected = signal_hash(signal)
        if any(str(r.get("signal_hash", "")).lower() != expected for r in responses):
            raise WorldIDError("proof was not made for this request")
        kinds = {r.get("identifier") for r in responses}
        credential = next((c for c in self.allowed if c in kinds), None)
        if credential is None:  # the page runs on the user's machine and can be changed: enforce the policy here
            raise WorldIDError(f"credential not accepted (need one of {', '.join(self.allowed)})")
        r = self.http.post(VERIFY_URL.format(rp_id=self.rp_id), json=result)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code != 200 or not body.get("success"):
            raise WorldIDError(f"World rejected the proof: {body.get('code') or r.status_code}")
        # The person is the nullifier of the allowed credential, as confirmed by World; never just the first one.
        confirmed = next((x for x in body.get("results", [])
                          if x.get("identifier") == credential and x.get("success") and x.get("nullifier")), None)
        if confirmed is None:
            raise WorldIDError(f"World did not confirm the {credential} credential")
        return to_bytes32_hex(confirmed["nullifier"])
