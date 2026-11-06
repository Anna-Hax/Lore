"""The only way Lore's agents call a model (BUILD_PLAN.md §2.1).

Every call is a private, TEE-verified run on the 0G Compute Router, and its
provider signature is re-checked by us before the output is used. There is no
non-private code path on purpose.
"""

import json
import re
import time
from datetime import UTC, datetime
from typing import Callable

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct
from lore_shared.canonical import canonical_hash

ROUTER = "https://router-api.0g.ai/v1"
# The Router always end-to-end encrypts private requests ("x-0g-e2ee: sealed", spike S1/S2, 2026-11-06). The TEE then
# signs hashes of the encrypted request and response instead of the plaintext output.
E2EE_SIGNED = re.compile(r"zg-sig-v1/e2ee-ct:[0-9a-f]{64}:[0-9a-f]{64}")
PRIVATE_HEADERS = {"X-0G-Provider-Trust-Mode": "private"}
SIGNATURE_FRESH_SECONDS = 600

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


def check_signature(signed_text: str, signature: str, expected_signer: str, output: str) -> tuple[str, str]:
    """Raise ZGError unless the provider's on-chain TEE signer signed this exchange.

    Returns (signer, binding). binding is "plaintext" when the TEE signed exactly `output`, or "e2ee-ciphertext" when
    it signed the end-to-end encrypted exchange (zg-sig-v1/e2ee-ct:<request hash>:<response hash>); the plaintext is
    then not bound by the signature, and receipts say so.
    """
    try:
        signer = recover_signer(signed_text, signature)
    except Exception as e:  # malformed signature
        raise ZGError(f"unrecoverable signature: {e}") from e
    if signer.lower() != expected_signer.lower():
        raise ZGError(f"signer {signer} is not the provider's TEE signer {expected_signer}")
    if signed_text == output:
        return signer, "plaintext"
    if E2EE_SIGNED.fullmatch(signed_text):
        return signer, "e2ee-ciphertext"
    raise ZGError("signed text does not match the output we received")


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
    # Providers keep signatures for 15-30 min (spike S3): an older paid response can no longer be verified, so it is
    # paid for again rather than retried against a signature that is gone.
    if paid is None or time.time() - paid.get("paid_at", 0) > SIGNATURE_FRESH_SECONDS:
        paid = _pay(http, body, api_key, retries, sleep)
        paid["paid_at"] = time.time()
        if cache:
            cache.put(request_hash, paid)
    if paid["tee_verified"] is False:  # the Router omits the field today; only an explicit False is a verdict
        raise ZGError("router did not verify the TEE signature (tee_verified=False)")
    output = paid["output"]
    try:
        url, tee_signer = provider_info(paid["provider"])
        sig = http.get(f"{url}/v1/proxy/signature/{paid['chat_id']}", params={"model": model})
        sig.raise_for_status()
        sig = sig.json()
        signer, binding = check_signature(sig["text"], sig["signature"], tee_signer, output)
    except ZGError:
        raise
    except Exception as e:  # already paid: never let this look transient (it would be retried for free, forever)
        raise ZGError(f"could not verify a paid response: {e!r}") from e

    receipt = {
        "model": model,
        "provider": paid["provider"],
        "chat_id": paid["chat_id"],
        "trust_mode": "private",
        "tee_verified": True,  # we checked the TEE signature against the provider's on-chain signer ourselves
        "router_tee_verified": paid["tee_verified"],
        "binding": binding,
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


def _busy(r) -> bool:
    """Nothing was charged and trying again later is safe: no private provider right now, or rate limited (429)."""
    return r.status_code == 429 or (r.status_code == 503 and "no_provider_for_trust_mode" in r.text)


def _pay(http, body, api_key, retries, sleep) -> dict:
    """The one paid step: a private completion from the router. Returns what we need to verify it later."""
    headers = {"Authorization": f"Bearer {api_key}", **PRIVATE_HEADERS}
    for attempt in range(retries):
        r = http.post(f"{ROUTER}/chat/completions", json=body, headers=headers)
        if _busy(r):
            sleep(2**attempt)  # wait for a private provider or rate limit; never downgrade the trust tier
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


def embed(
    text: str,
    *,
    model: str,
    api_key: str,
    provider_info: ProviderInfo,
    http: httpx.Client | None = None,
    retries: int = 5,
    sleep: Callable[[float], None] = time.sleep,
) -> list[float]:
    """One private embedding from the Router, used only for similarity scores (never shown to users).

    Same rules as call(): private mode, and the provider's TEE signature over the (end-to-end encrypted) exchange
    must come from the signer in its on-chain Service record. The vector itself is not bound by that signature.
    """
    http = http or httpx.Client(timeout=120)
    headers = {"Authorization": f"Bearer {api_key}", **PRIVATE_HEADERS}
    body = {"model": model, "input": [text], "verify_tee": True}
    for attempt in range(retries):
        r = http.post(f"{ROUTER}/embeddings", json=body, headers=headers)
        if _busy(r):
            sleep(2**attempt)
            continue
        r.raise_for_status()
        break
    else:
        raise ZGUnavailable("no private (TeeML) embedding provider available")
    data = r.json()
    trace = data.get("x_0g_trace") or {}
    if trace.get("tee_verified") is False:
        raise ZGError("router did not verify the TEE signature (tee_verified=False)")
    vector = data["data"][0]["embedding"]
    chat_id = r.headers.get("ZG-Res-Key") or data.get("id")
    try:
        url, tee_signer = provider_info(trace["provider"])
        sig = http.get(f"{url}/v1/proxy/signature/{chat_id}", params={"model": model})
        sig.raise_for_status()
        sig = sig.json()
        check_signature(sig["text"], sig["signature"], tee_signer, json.dumps(vector))
    except ZGError:
        raise
    except Exception as e:
        raise ZGError(f"could not verify a paid embedding: {e!r}") from e
    return vector
