import json

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak

from lore_mcp.proof import badge, check

TEE, OTHER = Account.create(), Account.create()
OUT = '{"title": "x"}'


def receipt(signer=TEE, text=OUT, **kw):
    sig = signer.sign_message(encode_defunct(text=text)).signature.to_0x_hex()
    h = "0x" + keccak(json.dumps(OUT, separators=(",", ":"), ensure_ascii=False).encode()).hex()
    return {"model": "m", "provider": "0xP", "trust_mode": "private", "tee_verified": True,
            "signed_text": text, "signature": sig, "signer": TEE.address, "response_hash": h, **kw}


def test_valid_receipt_passes_against_onchain_signer():
    assert check(receipt(), TEE.address)["status"] == "pass"


def test_without_onchain_signer_it_is_incomplete_not_pass():
    assert check(receipt(), None)["status"] == "incomplete"


def test_tampering_is_caught():
    assert "signer_matches_receipt" in check(receipt(signer=OTHER), TEE.address)["failed"]
    assert "output_matches_signature" in check(receipt(text='{"title": "y"}'), TEE.address)["failed"]
    assert "signer_matches_onchain" in check(receipt(), OTHER.address)["failed"]
    assert "private_mode" in check(receipt(trust_mode="standard"), TEE.address)["failed"]


def test_badge():
    assert badge(receipt()) == "[TEE-verified · private · model m · provider 0xP]"


def test_claim_must_match_the_signed_output():
    r = receipt()
    assert check(r, TEE.address, {"title": "x"})["status"] == "pass"
    bad = check(r, TEE.address, {"title": "something Lore made up"})
    assert bad["status"] == "fail" and "output_matches_claim" in bad["failed"]
    assert "DOES NOT MATCH" in badge(r, {"title": "nope"}) and "matches signed output" in badge(r, {"title": "x"})
