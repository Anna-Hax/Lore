"""Offline tests for zg against a fake 0G router and a fake TEE provider."""

import httpx
import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

import zg

TEE = Account.create()      # the provider's enclave key
IMPOSTOR = Account.create()
PROVIDER_URL = "https://provider.example"
OUTPUT = '{"relevant": true}'


def fake_network(*, tee_verified=True, signed_text=OUTPUT, signer=TEE, busy=0, seen=None, sig_down=0):
    """A MockTransport playing the router and the provider's signature endpoint."""
    state = {"busy": busy, "sig_down": sig_down}

    def handler(req: httpx.Request):
        if seen is not None:
            seen.append(req)
        if req.url.path.endswith("/chat/completions"):
            if state["busy"]:
                state["busy"] -= 1
                return httpx.Response(503, json={"error": {"code": "no_provider_for_trust_mode"}})
            return httpx.Response(
                200,
                headers={"ZG-Res-Key": "chat-1"},
                json={
                    "id": "body-id",
                    "choices": [{"message": {"content": OUTPUT}}],
                    "x_0g_trace": {"tee_verified": tee_verified, "provider": "0xProvider"},
                },
            )
        assert req.url.path == "/v1/proxy/signature/chat-1"
        if state["sig_down"]:
            state["sig_down"] -= 1
            raise httpx.ConnectError("provider signature endpoint unreachable")
        sig = signer.sign_message(encode_defunct(text=signed_text)).signature.to_0x_hex()
        return httpx.Response(200, json={"text": signed_text, "signature": sig})

    return httpx.Client(transport=httpx.MockTransport(handler))


def run(http, **kw):
    return zg.call(
        "some-teeml-model", [{"role": "user", "content": "hi"}],
        prompt_version="v1", api_key="k",
        provider_info=lambda p: (PROVIDER_URL, TEE.address),
        http=http, sleep=lambda s: None, **kw,
    )


def test_happy_path_builds_a_verified_private_receipt():
    out, r = run(fake_network())
    assert out == OUTPUT
    assert r["trust_mode"] == "private" and r["tee_verified"] and r["signer_matches_onchain"]
    assert r["signer"] == TEE.address and r["chat_id"] == "chat-1" and r["provider"] == "0xProvider"
    assert r["request_hash"].startswith("0x") and "hi" not in r["request_hash"]


def test_every_router_request_is_private_and_asks_for_verification():
    seen = []
    run(fake_network(busy=2, seen=seen))
    router_calls = [q for q in seen if q.url.path.endswith("/chat/completions")]
    assert len(router_calls) == 3
    for q in router_calls:
        assert q.headers["X-0G-Provider-Trust-Mode"] == "private"
        assert b'"verify_tee":true' in q.content.replace(b" ", b"")


def test_no_private_provider_raises_instead_of_downgrading():
    with pytest.raises(zg.ZGError, match="no private"):
        run(fake_network(busy=99), retries=3)


def test_unverified_run_is_rejected():
    with pytest.raises(zg.ZGError, match="tee_verified"):
        run(fake_network(tee_verified=False))


def test_signature_from_wrong_key_is_rejected():
    with pytest.raises(zg.ZGError, match="not the provider's TEE signer"):
        run(fake_network(signer=IMPOSTOR))


def test_signed_text_not_matching_output_is_rejected():
    with pytest.raises(zg.ZGError, match="does not match"):
        run(fake_network(signed_text='{"relevant": false}'))


def test_a_failure_after_payment_is_not_transient_and_a_retry_never_pays_again():
    import jobs

    seen, cache = [], {}

    class Cache:
        get = staticmethod(cache.get)
        put = staticmethod(cache.__setitem__)

    http = fake_network(sig_down=1, seen=seen)
    with pytest.raises(zg.ZGError) as e:
        run(http, cache=Cache)
    assert not isinstance(e.value, jobs.TRANSIENT)  # the job queue counts it, so it can't loop for free
    out, r = run(http, cache=Cache)  # retry: signature endpoint back
    assert out == OUTPUT and r["signer"] == TEE.address
    assert len([q for q in seen if q.url.path.endswith("/chat/completions")]) == 1  # paid exactly once


E2EE_TEXT = "zg-sig-v1/e2ee-ct:" + "ab" * 32 + ":" + "cd" * 32


def test_router_without_tee_verified_field_is_accepted_after_our_own_check():
    # Live Router responses (2026-11-06) carry no x_0g_trace.tee_verified; our signer check is the verdict.
    _, r = run(fake_network(tee_verified=None))
    assert r["tee_verified"] is True and r["router_tee_verified"] is None


def test_e2ee_signature_is_accepted_and_recorded_as_ciphertext_binding():
    # The Router always seals private requests, so the TEE signs ciphertext hashes, not the plaintext.
    out, r = run(fake_network(signed_text=E2EE_TEXT))
    assert out == OUTPUT and r["binding"] == "e2ee-ciphertext" and r["signed_text"] == E2EE_TEXT


def test_e2ee_signature_from_wrong_key_is_still_rejected():
    with pytest.raises(zg.ZGError, match="not the provider's TEE signer"):
        run(fake_network(signed_text=E2EE_TEXT, signer=IMPOSTOR))


def fake_embed_network(*, signer=TEE, signed_text=E2EE_TEXT):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            assert request.headers["X-0G-Provider-Trust-Mode"] == "private"
            return httpx.Response(200, headers={"ZG-Res-Key": "emb-1"},
                                  json={"data": [{"embedding": [0.1, 0.2]}], "x_0g_trace": {"provider": "0xProvider"}})
        sig = signer.sign_message(encode_defunct(text=signed_text)).signature.to_0x_hex()
        return httpx.Response(200, json={"text": signed_text, "signature": sig})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_embed_is_private_and_signature_checked():
    vec = zg.embed("t", model="m", api_key="k", provider_info=lambda p: (PROVIDER_URL, TEE.address), http=fake_embed_network())
    assert vec == [0.1, 0.2]
    with pytest.raises(zg.ZGError, match="not the provider's TEE signer"):
        zg.embed("t", model="m", api_key="k", provider_info=lambda p: (PROVIDER_URL, TEE.address),
                 http=fake_embed_network(signer=IMPOSTOR))


def test_rate_limit_backs_off_and_then_raises_unavailable_not_a_paid_failure():
    def handler(request):
        return httpx.Response(429, json={"error": "rate limited"})
    with pytest.raises(zg.ZGUnavailable):
        run(httpx.Client(transport=httpx.MockTransport(handler)))


def test_a_cached_response_older_than_its_signature_window_is_paid_again(monkeypatch):
    seen, cache = [], {}

    class Cache:
        get = staticmethod(cache.get)
        put = staticmethod(cache.__setitem__)

    http = fake_network(seen=seen)
    run(http, cache=Cache)
    (key,) = cache
    cache[key]["paid_at"] -= zg.SIGNATURE_FRESH_SECONDS + 1  # the provider has dropped that signature by now
    run(http, cache=Cache)
    assert len([q for q in seen if q.url.path.endswith("/chat/completions")]) == 2
