"""World ID Agent Pass: OIDC login and human checkpoints, against a fake World IdP that signs real RS256 ID tokens."""

import time
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from gateway.app import create_app
from gateway.service import LoreError
from gateway.worldidp import WorldIdP, person_of
from tests.fakes import FakeChain, FakeContent, FakeStorage

ISS, CLIENT, SECRET = "https://idp.test", "client-1", "s3cret"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
ORB = "https://world.org/oidc/acr/orb"


class FakeIdP:
    """World IdP's discovery + token endpoint. `next` controls the ID token the next code exchange returns."""

    def __init__(self, clock):
        self.clock, self.codes, self.next = clock, {}, {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(200, json={"issuer": ISS, "authorization_endpoint": f"{ISS}/authorize",
                                             "token_endpoint": f"{ISS}/token", "jwks_uri": f"{ISS}/jwks"})
        if request.url.path == "/token":
            assert request.headers["authorization"].startswith("Basic ")  # client_secret_basic
            form = parse_qs(request.content.decode())
            code = form["code"][0]
            if code not in self.codes or form.get("code_verifier") is None:
                return httpx.Response(400, json={"error": "invalid_grant"})
            nonce = self.codes.pop(code)
            overrides = dict(self.next)
            key = overrides.pop("_key", KEY)
            claims = {"iss": ISS, "aud": CLIENT, "sub": "sub-alice", "iat": self.clock["t"], "exp": self.clock["t"] + 300,
                      "nonce": nonce, "acr": ORB, "auth_time": self.clock["t"], **overrides}
            return httpx.Response(200, json={"id_token": jwt.encode(claims, key, "RS256")})
        return httpx.Response(404)

    def approve(self, authorize_url: str) -> dict:
        """What the browser brings back after the person completes World ID: code + state (+ iss)."""
        q = parse_qs(urlparse(authorize_url).query)
        code = f"code-{len(self.codes)}"
        self.codes[code] = q["nonce"][0]
        return {"code": code, "state": q["state"][0], "iss": ISS}


class Jwks:
    def get_signing_key_from_jwt(self, token):
        return type("K", (), {"key": KEY.public_key()})()


class RecordingSigner:
    def __init__(self):
        self.txs = []

    def send_all(self, txs):
        self.txs += txs
        return [f"0xhash{i}" for i in range(len(txs))]


@pytest.fixture
def env(tmp_path):
    clock = {"t": int(time.time())}
    fake = FakeIdP(clock)
    idp = WorldIdP(ISS, CLIENT, SECRET, "https://lore.test/login/callback",
                   http=httpx.Client(transport=httpx.MockTransport(fake.handler)), now=lambda: clock["t"], jwks_client=Jwks())
    chain = FakeChain()
    app = create_app(str(tmp_path / "gw.db"), chain, FakeContent(), FakeStorage(), now=lambda: clock["t"],
                     service_token="t", public_url="https://lore.test", idp=idp, approve_base="https://lore.test")
    svc = app.state.service
    svc.signer = RecordingSigner()
    alice = person_of(ISS, "sub-alice")
    with svc.tx() as conn:
        conn.execute("INSERT INTO persons VALUES (?, ?)", ("0x" + "aa" * 20, alice))
        conn.execute("INSERT INTO turnkey_wallets (person, email, created_ms, address, sub_org, ready)"
                     " VALUES (?, 'a@example.com', 0, ?, 'sub-a', 1)", (alice, "0x" + "aa" * 20))  # Lore signs for it
    return type("Env", (), dict(app=app, svc=svc, fake=fake, clock=clock, alice=alice, client=TestClient(app)))


def start_checkpoint(env):
    held = env.svc.checkpoint(env.alice, "pay 5 0G for topic 1", env.svc.prepare_buy(env.alice, 1))
    assert held["human_approval_required"] and env.svc.signer.txs == []  # nothing signed yet
    cid = held["checkpoint_id"]
    r = env.client.get(f"/checkpoint/{cid}/start", follow_redirects=False)
    assert r.status_code == 303
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["max_age"] == ["0"] and q["prompt"] == ["login"] and q["code_challenge_method"] == ["S256"]
    return cid, r.headers["location"]


def callback(env, params):
    return env.client.get("/login/callback", params=params, follow_redirects=False)


def test_approved_checkpoint_sends_once(env):
    cid, url = start_checkpoint(env)
    assert callback(env, env.fake.approve(url)).status_code == 200
    out = env.svc.continue_action(env.alice, cid)
    assert out["status"] == "sent" and [t["description"] for t in env.svc.signer.txs] == ["Access.buy"]
    with pytest.raises(LoreError, match="used"):
        env.svc.continue_action(env.alice, cid)  # single use
    assert len(env.svc.signer.txs) == 1


def test_pending_checkpoint_sends_nothing(env):
    cid, _ = start_checkpoint(env)
    assert env.svc.continue_action(env.alice, cid)["status"] == "waiting_for_approval"
    assert env.svc.signer.txs == []


def test_cancelled_at_world_id_blocks_the_action(env):
    cid, url = start_checkpoint(env)
    state = parse_qs(urlparse(url).query)["state"][0]
    assert callback(env, {"error": "access_denied", "state": state}).status_code == 403
    with pytest.raises(LoreError, match="blocked: this action was denied"):
        env.svc.continue_action(env.alice, cid)
    assert env.svc.signer.txs == []


def test_person_can_deny_from_the_page(env):
    cid, _ = start_checkpoint(env)
    env.client.get(f"/checkpoint/{cid}/deny")
    with pytest.raises(LoreError, match="denied"):
        env.svc.continue_action(env.alice, cid)


def test_a_different_world_id_cannot_approve(env):
    cid, url = start_checkpoint(env)
    env.fake.next = {"sub": "sub-mallory"}
    assert callback(env, env.fake.approve(url)).status_code == 403
    with pytest.raises(LoreError, match="denied"):
        env.svc.continue_action(env.alice, cid)


def test_stale_authentication_is_not_a_fresh_approval(env):
    cid, url = start_checkpoint(env)
    env.fake.next = {"auth_time": env.clock["t"] - 3600}  # an old session, not a new World ID check
    assert callback(env, env.fake.approve(url)).status_code == 403
    with pytest.raises(LoreError, match="denied"):
        env.svc.continue_action(env.alice, cid)


def test_forged_or_mismatched_tokens_are_rejected(env):
    for bad in ({"_key": OTHER_KEY}, {"aud": "someone-else"}, {"nonce": "replayed"}, {"acr": "none"}):
        cid, url = start_checkpoint(env)
        env.fake.next = dict(bad)
        assert callback(env, env.fake.approve(url)).status_code == 403, bad
        with pytest.raises(LoreError, match="denied"):
            env.svc.continue_action(env.alice, cid)
    assert env.svc.signer.txs == []


def test_unapproved_checkpoint_expires_and_never_sends(env):
    cid, _ = start_checkpoint(env)
    env.clock["t"] += env.svc.CHECKPOINT_TTL + 1
    with pytest.raises(LoreError, match="expired"):
        env.svc.continue_action(env.alice, cid)
    assert env.svc.signer.txs == []


def test_an_unused_approval_expires(env):
    cid, url = start_checkpoint(env)
    callback(env, env.fake.approve(url))
    env.clock["t"] += env.svc.APPROVAL_TTL + 1
    with pytest.raises(LoreError, match="expired"):
        env.svc.continue_action(env.alice, cid)


def test_callback_state_is_single_use(env):
    _, url = start_checkpoint(env)
    params = env.fake.approve(url)
    assert callback(env, params).status_code == 200
    assert callback(env, params).status_code == 400  # replay


def test_login_goes_to_world_idp_and_never_offers_demo(env):
    with env.client as c:
        assert c.post("/login/demo?pending=x", json={"name": "a"}).status_code == 404


def test_any_account_mode_names_no_credential_class_and_records_what_came_back(env):
    fake = FakeIdP(env.clock)
    any_idp = WorldIdP(ISS, CLIENT, SECRET, "https://lore.test/login/callback", accept_acr=None, now=lambda: env.clock["t"],
                       http=httpx.Client(transport=httpx.MockTransport(fake.handler)), jwks_client=Jwks())
    url, attempt = any_idp.authorize_url(fresh=True)
    assert "claims" not in parse_qs(urlparse(url).query)
    fake.next = {"acr": "https://world.org/oidc/acr/device"}
    claims = any_idp.finish(attempt, fake.approve(url), fresh=True)
    assert claims["acr"].endswith("/device")


def test_credential_class_setting():
    from gateway.worldidp import ACCEPTED_ACR, parse_acr

    assert parse_acr(None) == ACCEPTED_ACR and parse_acr("any") is None
    assert parse_acr("orb, orb-face") == ("https://world.org/oidc/acr/orb", "https://world.org/oidc/acr/orb-face")
    for not_accepted in ("selfie", "selfie-face", "orb,selfie", "passport"):  # Lore is Orb-only
        with pytest.raises(ValueError):
            parse_acr(not_accepted)


# --- the local-signing fallback: a self-held wallet signs its own transactions, so no checkpoint applies ---
from eth_account import Account as _Account
from eth_account.messages import encode_defunct as _defunct

DAVE = _Account.create()
