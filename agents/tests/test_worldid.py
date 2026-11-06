import httpx
import pytest

from gateway.worldid import WorldID, WorldIDError, signal_hash

AGENT = "0xAbCdEf0000000000000000000000000000000001"


def world(handler, seen=None):
    def h(req):
        if seen is not None:
            seen.append(req)
        return handler(req)

    return WorldID("app_x", "rp_x", "lore-person", http=httpx.Client(transport=httpx.MockTransport(h)))


def result(signal=AGENT, action="lore-person", identifiers=("orb",)):
    return {"protocol_version": "4.0", "action": action, "nonce": "n",
            "responses": [{"identifier": i, "nullifier": "0x1", "proof": ["0x0"] * 5, "signal_hash": signal_hash(signal.lower())}
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
    with pytest.raises(WorldIDError, match="not made for this agent"):
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
    assert int(signal_hash(AGENT.lower()), 16) < 2 ** 248


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
