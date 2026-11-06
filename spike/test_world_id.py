"""World ID checks against the real SDK's outputs (evidence/world-idkit-4.6.0.json). Run from agents/:
    uv run pytest ../spike/test_world_id.py

xfail(strict) marks a known gap in the gateway: fixing it turns that test into a failure until the mark is removed.
"""

import json
import shutil
import sys
from pathlib import Path

import httpx
import pytest
from eth_utils import keccak

SPIKE = Path(__file__).parent
sys.path[:0] = [str(SPIKE), str(SPIKE.parent / "agents")]

import world_live  # noqa: E402
from gateway.app import LOGIN_PAGE  # noqa: E402
from gateway.worldid import WorldID, WorldIDError, signal_hash  # noqa: E402
from world_rp import hash_signal, rp_context, rp_message, rp_signature  # noqa: E402

SDK = json.loads((SPIKE / "evidence" / "world-idkit-4.6.0.json").read_text())
KEY = "0x" + keccak(text="lore world spike throwaway key, never funded or registered").hex()
SIGNAL = "0a1b2c3d4e5f60718293a4b5c6d7e8f9"
RP_ID = "rp_00000000000000ab"
gap = lambda why: pytest.mark.xfail(strict=True, reason=why)  # noqa: E731


def completion(name):
    return SDK["scenarios"][name]["completion"]


def gateway(result, seen=None):
    """A WorldID whose World API confirms every response in `result`."""
    def world(req):
        if seen is not None:
            seen.append(req)
        return httpx.Response(200, json={"success": True, "results": [
            {"identifier": r["identifier"], "success": True, "nullifier": r["nullifier"]} for r in result["responses"]]})

    return WorldID("app_x", RP_ID, "lore-person", http=httpx.Client(transport=httpx.MockTransport(world)))


@pytest.mark.parametrize("v", SDK["signing"], ids=lambda v: repr(v["action"]))
def test_python_signature_is_byte_identical_to_idkit(v):
    nonce = bytes.fromhex(v["nonce"].removeprefix("0x"))
    message = rp_message(nonce, v["createdAt"], v["expiresAt"], v["action"])
    assert "0x" + message.hex() == v["message"]
    assert rp_signature(KEY, message) == v["sig"]


@pytest.mark.parametrize("signal,expected", SDK["signal_hashes"].items())
def test_hash_signal_port_matches_idkit(signal, expected):
    assert hash_signal(signal) == expected


def test_gateway_hash_matches_idkit_for_the_login_ids_it_uses():
    assert signal_hash(SIGNAL) == SDK["signal_hashes"][SIGNAL]


@pytest.mark.skipif(not (SPIKE / "world" / "node_modules").is_dir() or not shutil.which("node"), reason="needs npm ci")
def test_real_idkit_accepts_the_python_rp_context_and_the_live_runner_works():
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        "success": True, "results": [{"identifier": "orb", "success": True, "nullifier": "0x1"}]})))
    reply = {"proof": "0x" + "11" * 256, "merkle_root": "0x" + "22" * 32, "nullifier_hash": "0x" + "33" * 31,
             "verification_level": "orb"}
    record, result = world_live.run_round(http, "app_staging_" + "0" * 31 + "a", RP_ID, KEY, "lore-person", "orbLegacy",
                                          "staging", fake_reply=reply, show=lambda _: None)
    assert record["signal_hash_matches"] and record["verify"]["success"] and result["protocol_version"] == "3.0"


def test_rp_context_has_the_fields_idkit_needs():
    assert set(rp_context(RP_ID, KEY, "lore-person")) == {"rp_id", "nonce", "created_at", "expires_at", "signature"}


@pytest.mark.parametrize("name", ["orb_legacy", "device_legacy", "proof_of_human_orb_fallback"])
def test_gateway_verifies_a_3_0_result_shaped_by_the_real_sdk(name):
    result = completion(name)["result"]
    seen = []
    person = gateway(result, seen).verify(result, SIGNAL)
    assert person == "0x00" + "33" * 31
    assert json.loads(seen[0].content) == result


def test_sdk_presets_ask_world_app_for_what_the_docs_say():
    s = SDK["scenarios"]
    assert s["orb_legacy"]["asked"]["verification_level"] == "orb"
    assert s["device_legacy"]["asked"]["verification_level"] == "device"
    assert s["proof_of_human_v4"]["asked"]["proof_requests"] == ["proof_of_human"]


def test_the_sdk_wraps_its_result_so_the_raw_completion_is_not_a_proof():
    envelope = completion("orb_legacy")
    assert set(envelope) == {"success", "result"}
    with pytest.raises(WorldIDError, match="different action"):
        gateway(envelope["result"]).verify(envelope, SIGNAL)


def test_idkit_refuses_the_login_pages_request_without_allow_legacy_proofs():
    assert SDK["page_exact_call"].startswith("allow_legacy_proofs is required")


@gap("gateway/worldid.py rp_context raises NotImplementedError, so /login/request returns 503")
def test_gateway_signs_rp_context():
    assert WorldID("app_x", RP_ID, "lore-person", signing_key=KEY, idkit_module="m").rp_context()["signature"]


@gap("gateway/app.py omits allow_legacy_proofs, so IDKit.request throws on the button click")
def test_login_page_sets_allow_legacy_proofs():
    assert "allow_legacy_proofs" in LOGIN_PAGE


@gap("gateway/app.py posts pollUntilCompletion's {success, result} whole, so verify rejects every real proof")
def test_login_page_unwraps_the_completion():
    assert "JSON.stringify(result)" not in LOGIN_PAGE or "const result = await request.pollUntilCompletion()" not in LOGIN_PAGE


@gap("gateway/app.py asks only for orbLegacy, so the Orb-or-device policy cannot get a device proof")
def test_login_page_can_ask_for_device():
    assert "deviceLegacy" in LOGIN_PAGE


def test_gateway_refuses_a_4_0_result_so_one_human_cannot_hold_two_person_ids():
    result = completion("proof_of_human_v4")["result"]
    assert result["protocol_version"] == "4.0"
    with pytest.raises(WorldIDError, match="credential not accepted"):
        gateway(result).verify(result, SIGNAL)


@gap("gateway/worldid.py forwards the client's `environment`; World's handling of staging proofs is undocumented")
def test_gateway_refuses_a_client_chosen_environment_before_calling_world():
    result = completion("orb_legacy")["result"]
    assert result["environment"] == "staging"
    seen = []
    with pytest.raises(WorldIDError):
        gateway(result, seen).verify(result, SIGNAL)
    assert seen == []


@gap("gateway/worldid.py hashes 0x-signals as text; IDKit hashes them as bytes (matters if a wallet becomes a signal)")
def test_gateway_hash_matches_idkit_for_a_wallet_signal():
    wallet = "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd"
    assert signal_hash(wallet) == SDK["signal_hashes"][wallet]
