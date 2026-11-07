"""What the web workspace and explorer read: per-person views, honest counts, and the gateway's entry points."""

import json

from eth_account import Account
from fastapi.testclient import TestClient

from tests.test_gateway import ALICE, BOB, B32, env, person, seed  # noqa: F401  (fixture + helpers)

ALICE2 = Account.create()  # a second wallet of Alice's person


def link(env, acct, who):
    with env.svc.tx() as conn:
        conn.execute("INSERT OR IGNORE INTO persons VALUES (?, ?)", (acct.address.lower(), person(who)))


def test_buyers_are_counted_per_person_and_new_topic_submissions_show_their_topic(env):
    seed(env)
    link(env, ALICE2, ALICE)
    env.ev("Bought", topicId=1, buyer=ALICE.address)
    env.ev("Bought", topicId=1, buyer=ALICE2.address)  # same person, second wallet
    env.ev("Bought", topicId=1, buyer=BOB.address)
    with TestClient(env.app) as c:
        data = c.get("/api/overview").json()
    topic = next(t for t in data["topics"] if t["topic_id"] == 1)
    assert topic["buyers"] == 2 and data["stats"]["purchases"] == 3  # 2 people, 3 passes
    sub1 = next(s for s in data["submissions"] if s["sub_id"] == 1)
    assert sub1["topic_id"] == 1  # submitted as "new topic" (0); its node is in topic 1


def test_approvals_are_only_the_callers_own(env):
    env.svc.approve_base = "https://lore.test"
    for who, action in ((ALICE, "pay 1 for topic 1"), (BOB, "pay 2 for topic 2")):
        with env.svc.tx() as conn:
            conn.execute("INSERT INTO checkpoints VALUES (?, ?, ?, '{}', 'pending', ?, NULL, NULL, NULL)",
                         (f"cp-{who.address[:6]}", person(who), action, env.clock["t"]))
    mine = env.svc.my_approvals(person(ALICE))
    assert [a["action"] for a in mine] == ["pay 1 for topic 1"]
    assert mine[0]["approve_url"].endswith("/checkpoint/" + mine[0]["checkpoint_id"])


def test_my_topics_lists_owned_and_contributed(env):
    seed(env)
    env.ev("Bought", topicId=1, buyer=BOB.address)
    env.chain.access = {(1, BOB.address.lower())}
    assert env.svc.my_topics(person(BOB)) == {"owned": [1], "contributed": []}
    assert env.svc.my_topics(person(ALICE)) == {"owned": [], "contributed": [1]}
    env.chain.access = set()  # e.g. banned: no live access, so not "owned"
    assert env.svc.my_topics(person(BOB))["owned"] == []


def test_agents_can_be_listed_and_revoked_only_by_their_person(env):
    now = env.clock["t"]
    with env.svc.tx() as conn:
        conn.execute("INSERT INTO oauth_clients VALUES ('c1', ?, ?)", (json.dumps({"client_name": "Claude Code"}), now))
        for token, who in (("t-alice", ALICE), ("t-bob", BOB)):
            conn.execute("INSERT INTO oauth_tokens VALUES (?, 'access', 'c1', ?, '[]', ?, NULL)", (token, person(who), now + 60))
    assert [a["name"] for a in env.svc.my_agents(person(ALICE))] == ["Claude Code"]
    assert env.svc.revoke_agent(person(ALICE), "c1") == {"revoked": 1}
    assert env.svc.my_agents(person(ALICE)) == [] and len(env.svc.my_agents(person(BOB))) == 1  # Bob unaffected


def test_entry_urls_redirect_to_the_site_and_pages_link_back(tmp_path):
    from gateway.app import create_app
    from tests.fakes import FakeChain, FakeContent, FakeStorage

    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<p>lore</p>")
    app = create_app(str(tmp_path / "g.db"), FakeChain(), FakeContent(), FakeStorage(), service_token="t",
                     public_url="https://lore.test", site_dir=str(site))
    with TestClient(app) as c:
        for path in ("/", "/app"):
            r = c.get(path, follow_redirects=False)
            assert r.status_code == 307 and r.headers["location"] == "/app/"
        assert c.get("/app/").status_code == 200
    from gateway.app import PAGE

    assert "/app/workspace.html#approvals" in PAGE and 'href="/app/"' in PAGE
