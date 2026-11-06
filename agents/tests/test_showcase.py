"""The labelled demo login and the public explorer API."""

import json

from fastapi.testclient import TestClient

from gateway.app import create_app, demo_person
from tests.fakes import FakeChain, FakeContent, FakeStorage
from tests.test_gateway import env, person, submit, seed, ALICE, BOB  # noqa: F401  (fixture + helpers)


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
    assert data["stats"]["topics"] >= 1 and data["params"]["node_value"] == env.chain.price
    blob = json.dumps(data)
    for text in ("alice research", "bob follow-up"):  # the seeded research texts never leave as plaintext
        assert text not in blob
    assert {s["sub_id"] for s in data["submissions"]} == {1, 2}
