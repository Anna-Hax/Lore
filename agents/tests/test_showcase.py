"""Wallet linking, the labelled demo login, and the public explorer API."""

import json

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient

from gateway.app import create_app, demo_person
from gateway.service import LoreError
from tests.fakes import FakeChain, FakeContent, FakeStorage
from tests.test_gateway import env, person, submit, seed, ALICE, BOB  # noqa: F401  (fixture + helpers)

DAVE = Account.create()


def sign(acct, text):
    return acct.sign_message(encode_defunct(text=text)).signature.to_0x_hex()


def test_link_wallet_needs_a_signature_from_that_wallet_over_that_person(env):
    me = person(DAVE)
    msg = env.svc.link_message(me, DAVE.address)
    assert DAVE.address in msg and me in msg and "16602" in msg
    with pytest.raises(LoreError, match="not from this wallet"):
        env.svc.link_wallet(me, DAVE.address, sign(ALICE, msg))
    with pytest.raises(LoreError, match="not from this wallet"):  # a signature for another person can't be reused
        env.svc.link_wallet(me, DAVE.address, sign(DAVE, env.svc.link_message(person(ALICE), DAVE.address)))
    out = env.svc.link_wallet(me, DAVE.address, sign(DAVE, msg))
    assert out["wallets"] == [DAVE.address.lower()]
    assert env.chain.sent[-1][:2] == ("PersonRegistry", "register")


def test_link_wallet_refuses_a_wallet_owned_by_someone_else(env):
    env.chain.persons[DAVE.address.lower()] = person(ALICE)
    with pytest.raises(LoreError, match="another person"):
        env.svc.link_wallet(person(DAVE), DAVE.address, sign(DAVE, env.svc.link_message(person(DAVE), DAVE.address)))


def test_demo_login_is_off_unless_asked_for_and_never_with_world_id(tmp_path):
    common = dict(service_token="t", public_url="https://lore.test")
    off = create_app(str(tmp_path / "a.db"), FakeChain(), FakeContent(), FakeStorage(), **common)
    with TestClient(off) as c:
        assert c.post("/login/demo?pending=x", json={"name": "a"}).status_code == 404
    with_world = create_app(str(tmp_path / "b.db"), FakeChain(), FakeContent(), FakeStorage(), world=object(),
                            demo_login=True, **common)
    with TestClient(with_world) as c:
        assert c.post("/login/demo?pending=x", json={"name": "a"}).status_code == 404
    on = create_app(str(tmp_path / "c.db"), FakeChain(), FakeContent(), FakeStorage(), demo_login=True, **common)
    with TestClient(on) as c:
        assert c.post("/login/demo?pending=nope", json={"name": "a"}).status_code == 404  # unknown login


def test_demo_person_is_a_bytes32_per_name():
    assert demo_person("Ada") == demo_person(" ada ") != demo_person("bob")
    assert len(demo_person("ada")) == 66


def test_public_overview_has_no_plaintext(env):
    seed(env)
    with TestClient(env.app) as c:
        r = c.get("/api/overview")
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "*"
    data = r.json()
    assert data["stats"]["topics"] >= 1 and data["params"]["topic_price"] == env.chain.price
    blob = json.dumps(data)
    for text in ("alice research", "bob follow-up"):  # the seeded research texts never leave as plaintext
        assert text not in blob
    assert {s["sub_id"] for s in data["submissions"]} == {1, 2}
