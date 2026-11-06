"""The only way Lore's agents call a model (BUILD_PLAN.md §2.1).

Every call is a private, TEE-verified run on the 0G Compute Router, and its
provider signature is re-checked by us before the output is used. There is no
non-private code path on purpose.
"""

import json
import time
from datetime import UTC, datetime
from typing import Callable

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak

ROUTER = "https://router-api.0g.ai/v1"
PRIVATE_HEADERS = {"X-0G-Provider-Trust-Mode": "private"}

# provider address -> (provider base url, TEE signer address from its on-chain Service record).
# ponytail: injected because the Service contract/method is pinned down by spike S (q2).
ProviderInfo = Callable[[str], tuple[str, str]]


class ZGError(Exception):
    """A model call that must not be used: unverified, unprivate or with a bad proof."""


class ZGUnavailable(ZGError):
    """No private (TeeML) provider right now. Temporary: try again later, never downgrade."""


def _hash(obj) -> str:
    # ponytail: swap for lore_shared.canonical_hash once P3 lands it; same canonical form.
    return "0x" + keccak(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hex()


def recover_signer(text: str, signature: str) -> str:
    """EIP-191 personal_sign recovery."""
    return Account.recover_message(encode_defunct(text=text), signature=signature)


def check_signature(signed_text: str, signature: str, expected_signer: str, output: str) -> str:
    """Raise ZGError unless the TEE signed exactly `output`. Returns the recovered signer."""
    try:
        signer = recover_signer(signed_text, signature)
    except Exception as e:  # malformed signature
        raise ZGError(f"unrecoverable signature: {e}") from e
    if signer.lower() != expected_signer.lower():
        raise ZGError(f"signer {signer} is not the provider's TEE signer {expected_signer}")
    # ponytail: exact match per the docs; spike S confirms the signed text format.
    if signed_text != output:
        raise ZGError("signed text does not match the output we received")
    return signer


def call(
    model: str,
    messages: list[dict],
    *,
    prompt_version: str,
    api_key: str,
    provider_info: ProviderInfo,
    http: httpx.Client | None = None,
    retries: int = 5,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[str, dict]:
    """Run one private, verified completion. Returns (output, InferenceReceipt)."""
    http = http or httpx.Client(timeout=120)
    body = {"model": model, "messages": messages, "temperature": 0, "verify_tee": True}
    headers = {"Authorization": f"Bearer {api_key}", **PRIVATE_HEADERS}

    for attempt in range(retries):
        r = http.post(f"{ROUTER}/chat/completions", json=body, headers=headers)
        if r.status_code == 503 and "no_provider_for_trust_mode" in r.text:
            sleep(2**attempt)  # wait for a private provider; never downgrade the trust tier
            continue
        r.raise_for_status()
        break
    else:
        raise ZGUnavailable("no private (TeeML) provider available")

    data = r.json()
    trace = data.get("x_0g_trace") or {}
    if trace.get("tee_verified") is not True:
        raise ZGError(f"router did not verify the TEE signature (tee_verified={trace.get('tee_verified')!r})")
    output = data["choices"][0]["message"]["content"]
    provider = trace["provider"]
    chat_id = r.headers.get("ZG-Res-Key") or data["id"]

    url, tee_signer = provider_info(provider)
    sig = http.get(f"{url}/v1/proxy/signature/{chat_id}", params={"model": model})
    sig.raise_for_status()
    sig = sig.json()
    signer = check_signature(sig["text"], sig["signature"], tee_signer, output)

    receipt = {
        "model": model,
        "provider": provider,
        "chat_id": chat_id,
        "trust_mode": "private",
        "tee_verified": True,
        "signed_text": sig["text"],
        "signature": sig["signature"],
        "signer": signer,
        "signer_matches_onchain": True,
        "request_hash": _hash(body),
        "response_hash": _hash(output),
        "prompt_version": prompt_version,
        "created_at": datetime.now(UTC).isoformat(),
    }
    return output, receipt


def json_out(output: str) -> dict:
    """Parse a model's JSON answer, tolerating a ```json fence around it."""
    text = output.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)
