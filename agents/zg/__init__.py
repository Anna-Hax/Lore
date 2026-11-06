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
from lore_shared.canonical import canonical_hash

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
    return canonical_hash(obj)  # P3's canonical JSON; gateway/proof.py's response_hash computes the same


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
    cache=None,
) -> tuple[str, dict]:
    """Run one private, verified completion. Returns (output, InferenceReceipt).

    cache (get(key)/put(key, value), e.g. jobs.PaidCache) stores every paid response the moment the router
    returns it, keyed by the request hash. A retry of the same request reuses it and only redoes the free
    signature check, so Lore never pays twice for one request. Failures before payment raise ZGUnavailable
    (free to retry); every failure after payment is a plain ZGError.
    """
    http = http or httpx.Client(timeout=120)
    body = {"model": model, "messages": messages, "temperature": 0, "verify_tee": True}
    request_hash = _hash(body)
    paid = cache.get(request_hash) if cache else None
    if paid is None:
        paid = _pay(http, body, api_key, retries, sleep)
        if cache:
            cache.put(request_hash, paid)
    if paid["tee_verified"] is not True:
        raise ZGError(f"router did not verify the TEE signature (tee_verified={paid['tee_verified']!r})")
    output = paid["output"]
    try:
        url, tee_signer = provider_info(paid["provider"])
        sig = http.get(f"{url}/v1/proxy/signature/{paid['chat_id']}", params={"model": model})
        sig.raise_for_status()
        sig = sig.json()
        signer = check_signature(sig["text"], sig["signature"], tee_signer, output)
    except ZGError:
        raise
    except Exception as e:  # already paid: never let this look transient (it would be retried for free, forever)
        raise ZGError(f"could not verify a paid response: {e!r}") from e

    receipt = {
        "model": model,
        "provider": paid["provider"],
        "chat_id": paid["chat_id"],
        "trust_mode": "private",
        "tee_verified": True,
        "signed_text": sig["text"],
        "signature": sig["signature"],
        "signer": signer,
        "signer_matches_onchain": True,
        "request_hash": request_hash,
        "response_hash": _hash(output),
        "prompt_version": prompt_version,
        "created_at": datetime.now(UTC).isoformat(),
    }
    return output, receipt


def _pay(http, body, api_key, retries, sleep) -> dict:
    """The one paid step: a private completion from the router. Returns what we need to verify it later."""
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
    return {"output": data["choices"][0]["message"]["content"], "provider": trace.get("provider"),
            "chat_id": r.headers.get("ZG-Res-Key") or data["id"], "tee_verified": trace.get("tee_verified")}


def json_out(output: str) -> dict:
    """Parse a model's JSON answer, tolerating a ```json fence around it."""
    text = output.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)
