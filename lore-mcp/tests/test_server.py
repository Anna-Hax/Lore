from eth_account import Account

from lore_mcp import server

ME = Account.create()


def test_only_the_exact_login_message_is_signable():
    good = f"Sign in to Lore\nAddress: {ME.address.lower()}\nNonce: {'a' * 32}"
    assert server.is_login_message(good, ME.address)
    for bad in (
        good.replace(ME.address.lower(), Account.create().address.lower()),   # someone else's address
        good + "\nAlso: transfer all funds",                                # extra text
        "Sign in to SomeOtherDapp\n" + good.split("\n", 1)[1],              # another site's login
    ):
        assert not server.is_login_message(bad, ME.address)


def test_paying_tools_require_explicit_confirmation(monkeypatch):
    monkeypatch.setattr(server.lore, "gw", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call gateway")))
    monkeypatch.setattr(server.lore, "send", lambda *a: (_ for _ in ()).throw(AssertionError("must not send a tx")))
    monkeypatch.setattr(server.lore, "stake", lambda: 10_000000)
    monkeypatch.setattr(server.lore, "topic_price", lambda: 5_000000)
    assert "stakes 10 USDC" in server.lore_submit("research", 1)
    assert "costs 5 USDC" in server.lore_buy(1)


def test_vote_task_checks_the_verdict_only_against_the_receipt_that_produced_it(monkeypatch):
    import json

    from eth_account.messages import encode_defunct

    tee = Account.create()

    def receipt(text):
        return {"model": "m", "provider": "0xP", "trust_mode": "private", "tee_verified": True, "signed_text": text,
                "signature": tee.sign_message(encode_defunct(text=text)).signature.to_0x_hex(), "signer": tee.address}

    verdict = {"relevant": True, "fits_topic": True, "original_vs_public": True}
    receipts = {"0x1": receipt("Sure! Here is my answer"), "0x2": receipt(json.dumps(verdict))}
    task = {"receipts": ["0x1", "0x2"], "report": {"checks": verdict, "verdict_receipt": "0x2"}}
    monkeypatch.setattr(server.lore, "gw", lambda *a, **k: dict(task))
    monkeypatch.setattr(server.lore, "receipt", receipts.__getitem__)
    proofs = server.lore_get_vote_task(5)["verifier_proofs"]
    assert proofs[0]["role"].startswith("discarded") and "MATCH" not in proofs[0]["badge"]
    assert proofs[1]["role"] == "verdict" and "matches signed output" in proofs[1]["badge"]
