"""Check a Lore InferenceReceipt: the TEE signature, the claimed output, and 0G's on-chain record of the signer.

The receipt, its signature and the provider's on-chain record are all public, so anyone can repeat this check
with any EIP-191 tool without trusting Lore; the hosted MCP's lore_check_proof runs it for convenience.
"""

import json

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak

LIMIT = (
    "What this proves: a TEE-attested 0G provider, registered on-chain as serving this model, "
    "produced and signed this exact output in private mode. The model name itself is not inside the signed text."
)
LIMIT_E2EE = (
    "What this proves: a TEE-attested 0G provider, registered on-chain as serving this model, handled this request "
    "privately and signed the end-to-end encrypted exchange. 0G's Router always encrypts private requests, so the TEE "
    "signs hashes of the ciphertext: the signature does not bind the plaintext output, and the model name is not "
    "inside the signed text."
)


def e2ee(receipt: dict) -> bool:
    return receipt.get("binding") == "e2ee-ciphertext" or receipt.get("signed_text", "").startswith("zg-sig-v1/e2ee-ct:")


def response_hash(text: str) -> str:
    """Same canonical hash Lore's agents put in the receipt."""
    return "0x" + keccak(json.dumps(text, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hex()


def _signed_json(text: str):
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        return json.loads(t)
    except ValueError:
        return None


def claim_matches(receipt: dict, claim: dict) -> bool:
    """True if the model's signed output says exactly what Lore claims it said (e.g. the title shown to you)."""
    signed = _signed_json(receipt.get("signed_text", ""))
    if not isinstance(signed, dict):
        return False
    # The curator signs node and topic metadata in one output: {"node": {...}, "topic": {...}}.
    return any(isinstance(d, dict) and all(d.get(k) == v for k, v in claim.items()) for d in [signed, *signed.values()])


def check(receipt: dict, onchain_signer: str | None, claim: dict | None = None) -> dict:
    """onchain_signer: the provider's teeSignerAddress read from 0G's on-chain Service record (None = unknown).
    claim: what Lore says this model call produced (a title/description, or verifier verdicts); None = not checked.
    """
    try:
        recovered = Account.recover_message(encode_defunct(text=receipt["signed_text"]), signature=receipt["signature"])
    except Exception:
        recovered = None
    checks = {
        "signature_valid": recovered is not None,
        "signer_matches_receipt": recovered is not None and recovered.lower() == receipt["signer"].lower(),
        "output_matches_signature": None if e2ee(receipt)
        else response_hash(receipt["signed_text"]) == receipt["response_hash"],
        "private_mode": receipt.get("trust_mode") == "private",
        "tee_verified_by_router": receipt.get("tee_verified") is True,
        "signer_matches_onchain": None if onchain_signer is None
        else recovered is not None and recovered.lower() == onchain_signer.lower(),
        "output_matches_claim": None if claim is None or e2ee(receipt) else claim_matches(receipt, claim),
    }
    failed = [k for k, v in checks.items() if v is False]
    status = "fail" if failed else ("incomplete" if checks["signer_matches_onchain"] is None else "pass")
    return {
        "status": status, "failed": failed, "checks": checks,
        "model": receipt.get("model"), "provider": receipt.get("provider"),
        "prompt_version": receipt.get("prompt_version"), "binding": "e2ee-ciphertext" if e2ee(receipt) else "plaintext",
        "what_this_proves": LIMIT_E2EE if e2ee(receipt) else LIMIT,
    }


def badge(receipt: dict, claim: dict | None = None) -> str:
    """One line shown next to every verdict, title and description."""
    if not receipt.get("tee_verified"):
        tee = "NOT verified"
    else:
        tee = "TEE-signed (encrypted exchange)" if e2ee(receipt) else "TEE-verified"
    priv = "private" if receipt.get("trust_mode") == "private" else "NOT private"
    if claim is None:
        match = ""
    elif e2ee(receipt):
        match = " · output not bound by the signature (E2EE)"
    else:
        match = " · matches signed output" if claim_matches(receipt, claim) else " · DOES NOT MATCH signed output"
    return f"[{tee} · {priv} · model {receipt.get('model')} · provider {receipt.get('provider')}{match}]"
