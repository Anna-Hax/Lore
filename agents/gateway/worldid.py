"""World ID 4.0 for the gateway: links an agent to the real person behind it.

World ID can't be verified on 0G (no World ID contracts there), so the gateway verifies proofs with
World's API and records agent -> person in PersonRegistry. The person id is the proof's nullifier for
Lore's action: the same for every agent of one human, different across humans. The proof's signal is the
agent's address, so a proof made for one agent can't be replayed to register another.

Config (Developer Portal): WORLD_APP_ID, WORLD_RP_ID, WORLD_RP_SIGNING_KEY, WORLD_ACTION (default
"lore-person"), WORLD_IDKIT_MODULE (a pinned ESM URL of @worldcoin/idkit-core that lore-mcp's page loads).
The action must allow unlimited verifications per person, since each agent verifies.
"""

import httpx
from eth_utils import keccak

VERIFY_URL = "https://developer.world.org/api/v4/verify/{rp_id}"
# The decided policy: Orb or device. Order = preference when one proof carries both.
# ponytail: if spike W3 finds the nullifier differs across credential types, keep only one here, or one
# human could register two agents as two people.
ALLOWED_CREDENTIALS = ("orb", "device")


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
        self.idkit_module, self.allowed = idkit_module, allowed
        self.http = http or httpx.Client(timeout=30)

    def request(self, agent: str) -> dict:
        """What the user's browser needs to ask World App for a proof bound to this agent."""
        if not self.idkit_module:
            raise NotImplementedError("WORLD_IDKIT_MODULE is not set (pinned in spike W1)")
        return {"app_id": self.app_id, "rp_id": self.rp_id, "action": self.action, "signal": agent.lower(),
                "rp_context": self.rp_context(), "idkit_module": self.idkit_module}

    def rp_context(self) -> dict:
        # ponytail: blocked on spike W1. World ships signRequest only for JS (@worldcoin/idkit-core/signing)
        # and Go; port it to Python or run it as a tiny sidecar. Returns {rp_id, nonce, created_at, expires_at,
        # signature}, signed with WORLD_RP_SIGNING_KEY.
        raise NotImplementedError("World ID request signing pending spike W1")

    def verify(self, result: dict, agent: str) -> str:
        """Check an IDKit result is for our action, an allowed credential and bound to `agent`; verify it with
        World; return the person (the nullifier of the allowed credential World confirmed)."""
        responses = result.get("responses") or []
        if result.get("action") != self.action or not responses:
            raise WorldIDError("proof is for a different action")
        expected = signal_hash(agent.lower())
        if any(str(r.get("signal_hash", "")).lower() != expected for r in responses):
            raise WorldIDError("proof was not made for this agent")
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
