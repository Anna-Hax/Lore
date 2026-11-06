"""Gateway: indexer, vote gate, access checks, auth and the worker, over HTTP with fakes."""

import json
import threading

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient

from consts import MAX_CHARS
from gateway import tasks, worker
from gateway.app import create_app
from gateway.db import connect
from gateway.indexer import apply
from tests.fakes import FakeChain, FakeContent, FakeStorage

ALICE, BOB, CAROL, VERIFIER = (Account.create() for _ in range(4))
B32 = lambda h: bytes.fromhex(h.removeprefix("0x"))  # noqa: E731


@pytest.fixture
def env(tmp_path):
    chain, storage, clock = FakeChain(), FakeStorage(), {"t": 1_000}
    path = str(tmp_path / "gw.db")
    client = TestClient(create_app(path, chain, FakeContent(), storage, now=lambda: clock["t"]))
    db = connect(path)
    log = {"block": 0}

    def ev(name, **a):
        log["block"] += 1
        with db:
            apply(db, name, a, log["block"], 0, clock["t"])

    def login(acct):
        msg = client.post("/auth/nonce", json={"address": acct.address}).json()["message"]
        sig = acct.sign_message(encode_defunct(text=msg)).signature.to_0x_hex()
        tok = client.post("/auth/verify", json={"address": acct.address, "message": msg, "signature": sig}).json()["token"]
        return {"Authorization": f"Bearer {tok}"}

    return type("Env", (), dict(chain=chain, storage=storage, clock=clock, client=client, db=db, ev=ev,
                                login=login, path=path))


def seed(env):
    """Alice founds topic 1 (node 1); Bob then submits sub 2 to topic 1, which the verifier reports on."""
    c, a, b = env.client, env.login(ALICE), env.login(BOB)
    s1 = c.post("/ingest", json={"text": "alice research"}, headers=a).json()
    env.ev("Submitted", subId=1, topicId=0, submitter=ALICE.address, contentHash=B32(s1["content_hash"]), storageRoot=B32(s1["storage_root"]))
    env.ev("Reported", subId=1, **{"pass": True}, parents=[], reportHash=B32("0x" + "00" * 32), eligibleVoters=0)
    env.ev("NodeAdded", topicId=1, nodeId=1, contributor=ALICE.address, parents=[])
    env.ev("Finalized", subId=1, accepted=True, nodeId=1)
    env.chain.since[(1, ALICE.address.lower())] = env.clock["t"]

    env.clock["t"] += 10
    s2 = c.post("/ingest", json={"text": "bob follow-up", "topic_id": 1}, headers=b).json()
    report = {"parents": [{"node_id": 1, "score": 0.8}], "receipts": ["0xreceipt"], "passed": True}
    rroot = env.storage.upload(json.dumps(report).encode())
    env.ev("Submitted", subId=2, topicId=1, submitter=BOB.address, contentHash=B32(s2["content_hash"]), storageRoot=B32(s2["storage_root"]))
    env.ev("Reported", subId=2, **{"pass": True}, parents=[1], reportHash=B32(rroot), eligibleVoters=1)
    return a, b


# --- auth ---

def test_auth_rejects_missing_token_and_wrong_signer(env):
    assert env.client.get("/vote-tasks").status_code == 401
    msg = env.client.post("/auth/nonce", json={"address": ALICE.address}).json()["message"]
    forged = BOB.sign_message(encode_defunct(text=msg)).signature.to_0x_hex()
    body = {"address": ALICE.address, "message": msg, "signature": forged}
    assert env.client.post("/auth/verify", json=body).status_code == 401


def test_someone_else_requesting_a_nonce_does_not_cancel_your_sign_in(env):
    msg = env.client.post("/auth/nonce", json={"address": ALICE.address}).json()["message"]
    env.client.post("/auth/nonce", json={"address": ALICE.address})  # attacker
    sig = ALICE.sign_message(encode_defunct(text=msg)).signature.to_0x_hex()
    assert env.client.post("/auth/verify", json={"address": ALICE.address, "message": msg, "signature": sig}).status_code == 200


# --- vote gate and vote tasks ---

def test_contributor_must_vote_before_submitting(env):
    a, b = seed(env)
    c = env.client
    assert [t["sub_id"] for t in c.get("/vote-tasks", headers=a).json()] == [2]
    assert c.post("/ingest", json={"text": "alice again", "topic_id": 1}, headers=a).status_code == 409
    assert c.get("/vote-tasks", headers=b).json() == []  # submitter never votes on their own submission

    env.ev("Voted", subId=2, voter=ALICE.address, approve=True)
    assert c.get("/vote-tasks", headers=a).json() == []
    assert c.post("/ingest", json={"text": "alice again", "topic_id": 1}, headers=a).status_code == 200


def test_vote_task_is_watermarked_for_the_voter_and_only_shown_to_eligible_voters(env):
    a, _ = seed(env)
    body = env.client.get("/vote-tasks/2", headers=a).json()
    assert body["text"] == f"bob follow-up[wm:{ALICE.address.lower()}:-2]"  # voter copies: mark id -sub_id
    assert body["receipts"] == ["0xreceipt"] and [p["node_id"] for p in body["parents_meta"]] == [1]
    assert env.db.execute("SELECT wallet FROM vote_views WHERE sub_id=2").fetchone()[0] == ALICE.address.lower()
    assert env.client.get("/vote-tasks/2", headers=env.login(CAROL)).status_code == 403


def test_vote_window_closes_using_the_onchain_window(env):
    a, _ = seed(env)
    env.chain.window = 3600  # ADMIN shortened it on-chain; the gateway must not assume 24h
    env.clock["t"] += 3600
    env.chain.votable = set()  # and the chain's canVote now says no
    assert env.client.get("/vote-tasks", headers=a).json() == []
    assert env.client.get("/vote-tasks/2", headers=a).status_code == 403


# --- ingest ---

def test_ingest_can_be_retried_by_the_same_caller_until_submitted(env):
    a = env.login(ALICE)
    first = env.client.post("/ingest", json={"text": "draft"}, headers=a).json()
    assert env.client.post("/ingest", json={"text": "draft"}, headers=a).json() == first  # approve/submit failed; retry
    assert env.client.post("/ingest", json={"text": "draft"}, headers=env.login(BOB)).status_code == 409
    env.ev("Submitted", subId=9, topicId=0, submitter=ALICE.address,
           contentHash=B32(first["content_hash"]), storageRoot=B32(first["storage_root"]))
    assert env.client.post("/ingest", json={"text": "draft"}, headers=a).status_code == 409


def test_oversized_ingest_and_leak_are_rejected(env):
    a = env.login(ALICE)
    big = "x" * (MAX_CHARS + 1)
    assert env.client.post("/ingest", json={"text": big}, headers=a).status_code == 422
    assert env.client.post("/leaks", json={"topic_id": 1, "text": big}, headers=a).status_code == 422
    assert env.storage.blobs == {}


# --- reading ---

def test_reading_needs_access_and_is_watermarked_per_reader(env):
    seed(env)
    carol = env.login(CAROL)
    assert env.client.get("/topics/1/content", headers=carol).status_code == 403
    env.chain.access.add((1, CAROL.address.lower()))
    nodes = env.client.get("/topics/1/content", headers=carol).json()["nodes"]
    assert nodes[0]["text"] == f"alice research[wm:{CAROL.address.lower()}:1]"
    assert env.db.execute("SELECT wallet FROM deliveries").fetchone()[0] == CAROL.address.lower()


def test_reading_does_not_hold_the_write_lock_during_downloads(env):
    seed(env)
    carol = env.login(CAROL)
    env.chain.access.add((1, CAROL.address.lower()))
    other = connect(env.path)
    other.execute("PRAGMA busy_timeout=100")
    original = env.storage.download

    def slow_download(root):  # while the content endpoint downloads, another writer must get through
        with other:
            other.execute("INSERT OR REPLACE INTO cursor VALUES ('probe', 1)")
        return original(root)

    env.storage.download = slow_download
    assert env.client.get("/topics/1/content", headers=carol).status_code == 200


def test_a_connection_can_be_used_from_another_thread(tmp_path):
    """FastAPI opens the per-request connection and runs the endpoint on different threads.

    TestClient doesn't reproduce that, so test the property the API relies on directly.
    """
    conn, errors = connect(str(tmp_path / "t.db")), []

    def use():
        try:
            conn.execute("SELECT 1").fetchone()
        except Exception as e:
            errors.append(e)

    t = threading.Thread(target=use)
    t.start()
    t.join()
    assert errors == []


# --- internal ---

def test_internal_endpoints_need_a_lore_role_and_flag_ungated_submissions(env):
    seed(env)
    v = env.login(VERIFIER)
    assert env.client.get("/internal/plaintext/sub/2", headers=v).status_code == 403
    env.chain.roles.add(("VERIFIER", VERIFIER.address.lower()))
    got = env.client.get("/internal/plaintext/sub/2", headers=v).json()
    assert got["ingested"] and got["text"] == "bob follow-up" and got["status"] == "Reported"

    # Carol skips /ingest and submits on-chain directly: the verifier must see ingested=False.
    env.ev("Submitted", subId=3, topicId=1, submitter=CAROL.address, contentHash=B32("0x" + "ab" * 32), storageRoot=B32("0x" + "cd" * 32))
    assert env.client.get("/internal/plaintext/sub/3", headers=v).json()["ingested"] is False

    cands = env.client.get("/internal/candidates/1", headers=v).json()
    assert [n["node_id"] for n in cands["nodes"]] == [1]
    assert [p["sub_id"] for p in cands["pending"]] == [2]  # sub 3 is not ingested, so not a candidate


# --- indexer and worker ---

def test_indexer_is_idempotent(env):
    seed(env)
    with env.db:
        apply(env.db, "Voted", {"subId": 2, "voter": CAROL.address, "approve": True}, 1, 0, 0)  # block 1 already seen
    assert env.db.execute("SELECT COUNT(*) FROM votes").fetchone()[0] == 0


def test_finalizer_only_sends_what_the_chain_says_can_finalize(env):
    seed(env)
    assert tasks.finalizable(env.db, env.chain) == []  # sub 1 is already Accepted; chain says sub 2 can't yet
    env.chain.finalizable_ids = {2}
    worker.finalize_due(env.db, env.chain)
    assert env.chain.sent == [("Submissions", "finalize", 2)]


def test_chain_says_no_means_no_vote_task(env):
    a, _ = seed(env)
    env.chain.votable = set()  # e.g. alice became a contributor after the report: canVote is false
    assert env.client.get("/vote-tasks", headers=a).json() == []
    assert env.client.get("/vote-tasks/2", headers=a).status_code == 403


def test_worker_indexes_on_its_own_thread_in_batches(tmp_path):
    chain = FakeChain()
    chain.events = [(5, 0, "TopicCreated", {"topicId": 1}, 0), (3000, 0, "TopicCreated", {"topicId": 2}, 0)]
    chain.head = 3000
    path = str(tmp_path / "w.db")
    connect(path).close()

    def index_twice():  # the worker opens its own connection on its own thread
        db = connect(path)
        assert worker.sync(db, chain, start_block=0) == 1999
        assert worker.sync(db, chain, start_block=0) == 3000

    t = threading.Thread(target=index_twice)
    t.start()
    t.join()
    assert [r[0] for r in connect(path).execute("SELECT id FROM topics ORDER BY id")] == [1, 2]


def test_fill_meta_loads_json_named_by_the_onchain_root(env):
    seed(env)
    root = env.storage.upload(json.dumps({"title": "T"}).encode())
    env.ev("NodeMetaSet", nodeId=1, metaHash=B32(root))
    worker.fill_meta(env.db, env.storage)
    assert json.loads(env.db.execute("SELECT meta_json FROM nodes WHERE id=1").fetchone()[0]) == {"title": "T"}


def test_leak_matching_considers_buyers_and_voters(env):
    a, _ = seed(env)
    env.chain.access.add((1, CAROL.address.lower()))
    env.client.get("/topics/1/content", headers=env.login(CAROL))
    env.client.get("/vote-tasks/2", headers=a)
    assert sorted(worker.candidates_for(env.db, 1)) == sorted([(CAROL.address.lower(), 1), (ALICE.address.lower(), -2)])

    leaked = env.client.post("/leaks", json={"topic_id": 1, "text": "leaked"}, headers=env.login(BOB)).json()
    env.ev("LeakReported", reportId=7, topicId=1, reporter=BOB.address, evidenceHash=B32(leaked["evidence_hash"]))
    worker.match_leaks(env.db, env.chain, lambda text, cands: (ALICE.address.lower(), 9000), set())
    assert env.chain.sent == [("Reports", "recordMatch", 7, ALICE.address, 9000)]


def test_inbox_returns_vote_tasks_own_submissions_and_new_nodes_in_my_topics(env):
    a, b = seed(env)
    inbox = env.client.get("/inbox", headers=a).json()
    assert [t["sub_id"] for t in inbox["vote_tasks"]] == [2]
    assert inbox["submissions"] == [{"sub_id": 1, "topic_id": 0, "status": "Accepted", "node_id": 1}]
    assert [n["node_id"] for n in inbox["new_nodes"]] == [1]  # alice contributed to topic 1
    assert env.client.get("/inbox?since_node=1", headers=a).json()["new_nodes"] == []

    carol = env.login(CAROL)
    assert env.client.get("/inbox", headers=carol).json()["new_nodes"] == []  # not her topic
    env.ev("Bought", topicId=1, buyer=CAROL.address)
    assert [n["node_id"] for n in env.client.get("/inbox", headers=carol).json()["new_nodes"]] == [1]


def test_copied_content_is_never_decrypted_for_the_copiers_accomplices(env):
    """Carol ingests, but her submit fails; Bob copies her (hash, root) on-chain into Alice's topic."""
    a, _ = seed(env)
    stolen = env.client.post("/ingest", json={"text": "CAROL SECRET", "topic_id": 1}, headers=env.login(CAROL)).json()
    env.ev("Submitted", subId=3, topicId=1, submitter=BOB.address,
           contentHash=B32(stolen["content_hash"]), storageRoot=B32(stolen["storage_root"]))
    report = env.storage.upload(json.dumps({"parents": [], "receipts": [], "passed": False}).encode())
    env.ev("Reported", subId=3, **{"pass": False}, parents=[], reportHash=B32(report), eligibleVoters=1)

    task = env.client.get("/vote-tasks/3", headers=a).json()
    assert task["text"] is None and "CAROL" not in json.dumps(task)
    v = env.login(VERIFIER)
    env.chain.roles.add(("VERIFIER", VERIFIER.address.lower()))
    assert env.client.get("/internal/plaintext/sub/3", headers=v).json()["ingested"] is False
    assert 3 not in [p["sub_id"] for p in env.client.get("/internal/candidates/1", headers=v).json()["pending"]]


def test_an_old_ingest_cannot_be_used_to_skip_votes_assigned_later(env):
    seed(env)
    v = env.login(VERIFIER)
    env.chain.roles.add(("VERIFIER", VERIFIER.address.lower()))
    early = env.client.post("/ingest", json={"text": "prepared early", "topic_id": 1}, headers=env.login(CAROL)).json()
    env.clock["t"] += 3600  # vote tasks could have appeared meanwhile; she submits on-chain an hour later
    env.ev("Submitted", subId=4, topicId=1, submitter=CAROL.address,
           contentHash=B32(early["content_hash"]), storageRoot=B32(early["storage_root"]))
    assert env.client.get("/internal/plaintext/sub/4", headers=v).json()["ingested"] is False


def test_ingest_is_refused_while_the_indexer_is_behind(env):
    env.chain.head = 1_000  # gateway has indexed nothing yet
    r = env.client.post("/ingest", json={"text": "x"}, headers=env.login(ALICE))
    assert r.status_code == 503 and env.storage.blobs == {}


def test_a_failed_commit_is_an_error_not_a_silent_success(tmp_path, monkeypatch):
    import gateway.app as app_mod

    class CommitFails:
        def __init__(self, conn):
            self.conn = conn

        def __getattr__(self, name):
            return getattr(self.conn, name)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            raise RuntimeError("disk full")

    real = app_mod.connect
    monkeypatch.setattr(app_mod, "connect", lambda p: CommitFails(real(p)))
    client = TestClient(create_app(str(tmp_path / "g.db"), FakeChain(), FakeContent(), FakeStorage()),
                        raise_server_exceptions=False)
    assert client.post("/auth/nonce", json={"address": ALICE.address}).status_code == 500


def test_weak_leak_matches_are_never_recorded_on_chain(env):
    a, _ = seed(env)
    env.client.get("/vote-tasks/2", headers=a)
    leaked = env.client.post("/leaks", json={"topic_id": 1, "text": "unwatermarked text"}, headers=env.login(BOB)).json()
    env.ev("LeakReported", reportId=8, topicId=1, reporter=BOB.address, evidenceHash=B32(leaked["evidence_hash"]))
    worker.match_leaks(env.db, env.chain, lambda text, cands: (ALICE.address.lower(), 1200), set())
    assert env.chain.sent == []


def test_max_lag_tolerates_normal_indexing_jitter():
    from gateway.app import MAX_LAG

    galileo_block_seconds = 0.49  # measured on 0G Galileo
    # Between two index passes the chain moves SYNC_EVERY seconds; leave room for a slow pass too.
    assert MAX_LAG * galileo_block_seconds >= 5 * worker.SYNC_EVERY
