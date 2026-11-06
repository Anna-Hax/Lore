import httpx
import pytest

from gateway.worldid import WorldID, WorldIDError, signal_hash

AGENT = "login-0a1b2c3d"  # any signal: a login request id, or a lowercase wallet address


def world(handler, seen=None):
    def h(req):
        if seen is not None:
            seen.append(req)
        return handler(req)

    return WorldID("app_x", "rp_x", "lore-person", http=httpx.Client(transport=httpx.MockTransport(h)))


def result(signal=AGENT, action="lore-person", identifiers=("orb",)):
    return {"protocol_version": "4.0", "action": action, "nonce": "n",
            "responses": [{"identifier": i, "nullifier": "0x1", "proof": ["0x0"] * 5, "signal_hash": signal_hash(signal)}
                          for i in identifiers]}


def ok(req, results=(("orb", "0xabc"),)):
    return httpx.Response(200, json={"success": True, "results": [
        {"identifier": i, "success": True, "nullifier": n} for i, n in results]})


def test_valid_proof_returns_the_person_as_bytes32_hex():
    seen = []
    assert world(ok, seen).verify(result(), AGENT) == "0x" + "0" * 61 + "abc"
    assert seen[0].url.path == "/api/v4/verify/rp_x"


def test_a_proof_made_for_another_agent_is_rejected_before_calling_world():
    seen = []
    with pytest.raises(WorldIDError, match="not made for this request"):
        world(ok, seen).verify(result(signal="0x" + "9" * 40), AGENT)
    assert seen == []


def test_wrong_action_is_rejected():
    with pytest.raises(WorldIDError, match="different action"):
        world(ok).verify(result(action="other-app"), AGENT)


def test_world_rejecting_the_proof_is_an_error():
    def bad(req):
        return httpx.Response(400, json={"success": False, "code": "all_verifications_failed"})

    with pytest.raises(WorldIDError, match="all_verifications_failed"):
        world(bad).verify(result(), AGENT)


def test_signal_hash_fits_a_field_element():
    assert int(signal_hash(AGENT), 16) < 2 ** 248


def test_a_credential_outside_the_policy_is_rejected_before_calling_world():
    seen = []
    with pytest.raises(WorldIDError, match="credential not accepted"):
        world(ok, seen).verify(result(identifiers=("passport",)), AGENT)
    assert seen == []


def test_the_person_comes_from_the_allowed_credential_world_confirmed_not_the_first_one():
    both = lambda req: ok(req, results=(("passport", "0x999"), ("device", "0x2"), ("orb", "0x1")))  # noqa: E731
    assert world(both).verify(result(identifiers=("passport", "device", "orb")), AGENT) == "0x" + "0" * 63 + "1"


def test_world_must_confirm_the_allowed_credential():
    only_other = lambda req: ok(req, results=(("passport", "0x999"),))  # noqa: E731
    with pytest.raises(WorldIDError, match="did not confirm the orb"):
        world(only_other).verify(result(), AGENT)


def test_decimal_and_hex_nullifiers_give_the_same_person():
    from gateway.worldid import to_bytes32_hex

    assert to_bytes32_hex("255") == to_bytes32_hex("0xff") == "0x" + "0" * 62 + "ff"
    with pytest.raises(WorldIDError):
        to_bytes32_hex(str(2**256))


# --- RP request signing (spike W1): port of @worldcoin/idkit-server 1.2.0 signRequest ---
from eth_account import Account as _Account
from eth_account.messages import encode_defunct as _encode_defunct

from gateway.worldid import WorldID as _WorldID, hash_to_field, rp_signature_message, sign_request


def test_rp_message_layout_matches_idkit_server():
    nonce = bytes([0x11]) * 32
    msg = rp_signature_message(nonce, 1700000000, 1700000300, "lore-person")
    assert msg[0] == 1 and msg[1:33] == nonce
    assert int.from_bytes(msg[33:41], "big") == 1700000000 and int.from_bytes(msg[41:49], "big") == 1700000300
    assert msg[49:] == hash_to_field(b"lore-person") and len(msg) == 81
    assert hash_to_field(b"lore-person")[0] == 0  # keccak >> 8 always leaves the top byte zero
    assert len(rp_signature_message(nonce, 1, 2)) == 49  # no action


def test_signed_request_recovers_to_the_rp_signer_with_v_27_or_28():
    key = _Account.create()
    r = sign_request(key.key.hex(), "lore-person", now=lambda: 1700000000, entropy=lambda: b"\x07" * 32)
    assert r["expires_at"] - r["created_at"] == 300 and r["nonce"] == "0x" + hash_to_field(b"\x07" * 32).hex()
    sig = bytes.fromhex(r["sig"][2:])
    assert len(sig) == 65 and sig[64] in (27, 28)
    msg = rp_signature_message(bytes.fromhex(r["nonce"][2:]), r["created_at"], r["expires_at"], "lore-person")
    assert _Account.recover_message(_encode_defunct(primitive=msg), signature=sig) == key.address


def test_rp_context_has_the_shape_idkit_expects():
    key = _Account.create()
    ctx = _WorldID("app_x", "rp_y", "lore-person", key.key.hex()).rp_context()
    assert set(ctx) == {"rp_id", "nonce", "created_at", "expires_at", "signature"} and ctx["rp_id"] == "rp_y"
    req = _WorldID("app_x", "rp_y", "lore-person", key.key.hex()).request("pending-1")
    assert req["idkit_module"].startswith("https://cdn.jsdelivr.net/npm/@worldcoin/idkit-core@") and req["signal"] == "pending-1"
