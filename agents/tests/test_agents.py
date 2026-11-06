"""Verifier, curator and their persistent job queue, against a fake gateway, model and storage."""

import json

import pytest

import jobs as jobs_mod
from curator import agent as curator
from curator.agent import BadMeta, Memory, curate
from jobs import Jobs, NotReady, Skip
from tests.fakes import FakeChain
from verifier import agent as verifier
from verifier.agent import verify

TEXT = "Turnout in Maharashtra's 2024 assembly election by district. " * 12  # > 500 chars
NODE = "Coalition arithmetic in Maharashtra after the 2019 election. " * 12
VECS = {TEXT: [0.8, 0.6, 0.0], NODE: [1.0, 0.0, 0.0]}  # cosine 0.8: related, not a duplicate


class FakeGW:
    def __init__(self, sub=None, nodes=(), pending=(), synced=100, topic_id=1, status="Pending"):
        self.sub = {"topic_id": topic_id, "ingested": True, "text": TEXT, "status": status, "synced_block": synced}
        self.sub |= sub or {}
        self.c = {"synced_block": synced, "topic": {"title": "Maharashtra politics", "description": "d", "receipt": "0xr"},
                  "nodes": list(nodes), "pending": list(pending)}

    def plaintext(self, kind, iid):
        return self.sub

    def candidates(self, tid):
        return self.c


class FakeLLM:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, messages, version):
        self.calls.append((messages, version))
        a = self.answers.pop(0)
        return (a if isinstance(a, str) else json.dumps(a)), {"model": "m", "prompt_version": version}


def uploads():
    store = []
    return store, lambda obj: (store.append(obj), root(len(store)))[1]


def root(n: int) -> str:
    return f"0x{n:064x}"


OK = {"relevant": True, "fits_topic": True, "original_vs_public": True, "reasons": ["Solid district-level analysis."]}
node1 = {"node_id": 1, "text": NODE, "meta": {"title": "Coalitions"}}
embed = lambda t: VECS.get(t, [0, 0, 1])  # noqa: E731


# --- verifier ---

def test_valid_follow_up_passes_with_parent_and_receipt():
    store, up = uploads()
    llm = FakeLLM(OK)
    r = verify(7, gw=FakeGW(nodes=[node1]), embed=embed, llm=llm, upload_json=up)
    assert r["passed"] and r["parents"] == [1]
    assert r["report"]["receipts"] == [root(1)] and store[0]["prompt_version"] == "verify_v2"
    sent = json.loads(llm.calls[0][0][1]["content"])
    assert sent["closest_nodes"] == ["Coalitions"] and sent["submission"] == TEXT
    assert sent["topic"] == {"title": "Maharashtra politics", "description": "d"}  # no receipt/timestamps


def test_not_ingested_fails_without_calling_the_model():
    llm = FakeLLM()
    r = verify(7, gw=FakeGW(sub={"ingested": False, "text": None}), embed=embed, llm=llm, upload_json=uploads()[1])
    assert not r["passed"] and r["report"]["checks"]["ingested_by_gateway"] is False and llm.calls == []


def test_too_short_fails():
    r = verify(7, gw=FakeGW(sub={"text": "short"}), embed=embed, llm=FakeLLM(), upload_json=uploads()[1])
    assert not r["passed"] and r["report"]["checks"]["length"] is False


def test_earlier_pending_duplicate_wins_but_later_one_does_not():
    VECS["EARLIER"] = VECS["LATER"] = VECS[TEXT]
    earlier = verify(7, gw=FakeGW(pending=[{"sub_id": 5, "text": "EARLIER"}]), embed=embed, llm=FakeLLM(OK), upload_json=uploads()[1])
    assert not earlier["passed"] and earlier["report"]["checks"]["original_vs_pending"] is False
    later = verify(7, gw=FakeGW(pending=[{"sub_id": 9, "text": "LATER"}]), embed=embed, llm=FakeLLM(OK), upload_json=uploads()[1])
    assert later["passed"]


def test_model_rejection_fails_and_new_topic_gets_no_parents():
    r = verify(7, gw=FakeGW(nodes=[node1]), embed=embed, llm=FakeLLM({**OK, "relevant": False}), upload_json=uploads()[1])
    assert not r["passed"]
    r = verify(7, gw=FakeGW(topic_id=0), embed=embed, llm=FakeLLM(OK), upload_json=uploads()[1])
    assert r["passed"] and r["parents"] == []


def test_unusable_model_output_is_retried_once_then_fails_closed_with_a_reason():
    r = verify(7, gw=FakeGW(nodes=[node1]), embed=embed, llm=FakeLLM("I think this is fine.", OK), upload_json=uploads()[1])
    assert r["passed"] and len(r["report"]["receipts"]) == 2  # both model calls keep their proof
    r = verify(7, gw=FakeGW(nodes=[node1]), embed=embed, llm=FakeLLM("prose", {"relevant": True}), upload_json=uploads()[1])
    assert not r["passed"] and "did not return a usable verdict" in r["report"]["reasons"][-1]


def test_waits_for_gateway_and_skips_already_reported():
    with pytest.raises(NotReady):
        verify(7, gw=FakeGW(synced=5), embed=embed, llm=FakeLLM(OK), upload_json=uploads()[1], min_block=6)
    llm = FakeLLM()
    with pytest.raises(Skip):
        verify(7, gw=FakeGW(status="Reported"), embed=embed, llm=llm, upload_json=uploads()[1])
    assert llm.calls == []  # no paid model call for work already done


# --- job queue ---

def chain_with(event, key, ids):
    chain = FakeChain()
    chain.events = [(10 + i, 0, event, {key: i}, 0) for i in ids]
    chain.head = 10 + max(ids)
    return chain


def test_verifier_queue_survives_restart_without_redoing_work(tmp_path):
    chain, path = chain_with("Submitted", "subId", [1, 2]), str(tmp_path / "v.db")
    llm = FakeLLM(OK, OK)
    verifier.run(chain, Jobs(path), gw=FakeGW(nodes=[node1]), embed=embed, llm=llm,
                 upload_json=uploads()[1], start_block=0, once=True)
    assert [s[2] for s in chain.sent] == [1, 2] and len(llm.calls) == 2

    # Restart: same job db, nothing new on chain -> no model calls, no transactions.
    verifier.run(chain, Jobs(path), gw=FakeGW(nodes=[node1]), embed=embed, llm=llm,
                 upload_json=uploads()[1], start_block=0, once=True)
    assert len(chain.sent) == 2 and len(llm.calls) == 2


def test_failing_job_backs_off_then_goes_dead_and_can_be_requeued(tmp_path):
    clock = {"t": 1_000}
    chain, j = chain_with("Submitted", "subId", [1]), Jobs(str(tmp_path / "v.db"), now=lambda: clock["t"])
    calls = []

    def boom(i, b):
        calls.append(clock["t"])
        raise RuntimeError("storage upload rejected")

    run = lambda: jobs_mod.loop(j, chain, event="Submitted", key="subId", start_block=0, handle=boom, once=True)  # noqa: E731
    run()
    run()  # backing off: not retried immediately
    assert len(calls) == 1 and j.status(1)["next_try"] == 1_000 + 30
    for _ in range(jobs_mod.MAX_ATTEMPTS + 2):
        clock["t"] += 3600
        run()
    assert j.status(1)["status"] == "dead" and len(calls) == jobs_mod.MAX_ATTEMPTS
    assert j.requeue() == 1 and j.status(1)["status"] == "pending" and j.status(1)["attempts"] == 0


def test_transient_errors_never_count_as_attempts(tmp_path):
    import httpx
    import requests

    import zg

    chain, j = chain_with("Submitted", "subId", [1]), Jobs(str(tmp_path / "v.db"))
    errors = [zg.ZGUnavailable("no TeeML provider"), httpx.ConnectError("x"), requests.ConnectionError("rpc down")] * 5

    def flaky(i, b):
        raise errors.pop()

    while errors:
        jobs_mod.loop(j, chain, event="Submitted", key="subId", start_block=0, handle=flaky, once=True)
    assert j.status(1)["status"] == "pending" and j.status(1)["attempts"] == 0


def test_logs_are_read_in_bounded_batches(tmp_path):
    chain, j = chain_with("Submitted", "subId", [1]), Jobs(str(tmp_path / "v.db"))
    chain.head = 10_000
    seen = []
    orig = chain.logs
    chain.logs = lambda frm, to, only=None: (seen.append(to - frm + 1), orig(frm, to, only))[1]
    for _ in range(6):
        j.pull(chain, "Submitted", "subId", start_block=0)
    assert max(seen) <= 2000 and [r["id"] for r in j.pending()] == [1]


# --- curator ---

class CuratorGW:
    def __init__(self, gateway_nodes=(), meta_hash=None, synced=100):
        self.gateway_nodes, self.meta_hash, self.synced = list(gateway_nodes), meta_hash, synced

    def plaintext(self, kind, iid):
        return {"topic_id": 3, "ingested": True, "text": NODE, "meta_hash": self.meta_hash, "synced_block": self.synced}

    def topic(self, tid):  # the gateway lags: it knows the nodes but not their metadata yet
        return {"meta": None, "nodes": [{"node_id": n, "meta": None} for n in self.gateway_nodes]}


def meta(title="Coalitions in Maharashtra", n=350):
    return {"title": title, "description": "d" * n}


def test_curator_writes_node_and_topic_meta_with_receipts():
    store, up = uploads()
    r = curate(4, gw=CuratorGW([4]), llm=FakeLLM(meta(), meta("Maharashtra politics")), upload_json=up)
    assert r["node_meta"]["title"] == "Coalitions in Maharashtra" and r["node_meta"]["receipt"] == root(1)
    assert r["topic_meta"]["title"] == "Maharashtra politics" and r["topic_meta"]["node_count"] == 1
    assert [s.get("prompt_version") for s in store[:2]] == ["node_v1", "topic_v1"]


def test_curator_remembers_its_own_writes_when_the_gateway_lags(tmp_path):
    memory = Memory(Jobs(str(tmp_path / "c.db")).db)
    curate(4, gw=CuratorGW([4]), llm=FakeLLM(meta("First"), meta("Topic v1")), upload_json=uploads()[1], memory=memory)
    llm = FakeLLM(meta("Second"), meta("Topic v2"))
    r = curate(5, gw=CuratorGW([4, 5]), llm=llm, upload_json=uploads()[1], memory=memory)
    topic_call = json.loads(llm.calls[1][0][1]["content"])
    assert [n["title"] for n in topic_call["nodes"]] == ["First", "Second"]
    assert topic_call["current"]["title"] == "Topic v1" and r["topic_meta"]["node_count"] == 2


def test_curator_retries_once_then_gives_up_on_bad_output():
    r = curate(4, gw=CuratorGW([4]), llm=FakeLLM(meta(n=50), meta(), meta()), upload_json=uploads()[1])
    assert len(r["node_meta"]["description"]) == 350
    with pytest.raises(BadMeta):
        curate(4, gw=CuratorGW([4]), llm=FakeLLM("not json", meta(n=900)), upload_json=uploads()[1])


def test_curator_skips_nodes_that_already_have_metadata(tmp_path):
    chain, llm = chain_with("NodeAdded", "nodeId", [4]), FakeLLM()
    curator.run(chain, Jobs(str(tmp_path / "c.db")), gw=CuratorGW([4], meta_hash="0xabc"), llm=llm,
                upload_json=uploads()[1], start_block=0, once=True)
    assert llm.calls == [] and chain.sent == []


def test_gateway_lag_or_outage_never_kills_a_job(tmp_path):
    import httpx
    from eth_account import Account

    from gwclient import Gateway

    key = Account.create().key
    state = {"mode": "404"}

    def handler(req):
        if req.url.path == "/auth/nonce":
            return httpx.Response(200, json={"message": f"Sign in to Lore\nAddress: {Account.from_key(key).address.lower()}\nNonce: {'0' * 32}"})
        if req.url.path == "/auth/verify":
            return httpx.Response(200, json={"token": "t"})
        if state["mode"] == "down":
            raise httpx.ConnectError("gateway restarting")
        return httpx.Response(404 if state["mode"] == "404" else 503)

    gw = Gateway("http://gw", key.hex(), http=httpx.Client(base_url="http://gw", transport=httpx.MockTransport(handler)))
    chain, j = chain_with("Submitted", "subId", [7]), Jobs(str(tmp_path / "v.db"))
    for mode in ["404"] * 4 + ["503"] * 4 + ["down"] * 4:
        state["mode"] = mode
        verifier.run(chain, j, gw=gw, embed=embed, llm=FakeLLM(), upload_json=uploads()[1], start_block=0, once=True)
    row = j.status(7)
    assert row["status"] == "pending" and row["attempts"] == 0


def test_curator_resends_only_the_missing_transaction(tmp_path):
    clock = {"t": 0}
    chain, llm = chain_with("NodeAdded", "nodeId", [4]), FakeLLM(meta(), meta("Topic"))
    j = Jobs(str(tmp_path / "c.db"), now=lambda: clock["t"])
    real_send, calls = chain.send, {"n": 0}

    def flaky_send(contract, fn, *args):
        calls["n"] += 1
        if fn == "setTopicMeta" and calls["n"] == 2:
            raise RuntimeError("receipt timeout")
        real_send(contract, fn, *args)

    chain.send = flaky_send
    gw = CuratorGW([4])
    curator.run(chain, j, gw=gw, llm=llm, upload_json=uploads()[1], start_block=0, once=True)
    assert [s[1] for s in chain.sent] == ["setNodeMeta"] and j.status(4)["status"] == "pending"

    gw.meta_hash = "0xabc"  # the gateway has now indexed NodeMetaSet
    clock["t"] += 60  # past the backoff
    curator.run(chain, j, gw=gw, llm=llm, upload_json=uploads()[1], start_block=0, once=True)
    assert [s[1] for s in chain.sent] == ["setNodeMeta", "setTopicMeta"] and j.status(4)["status"] == "done"
    assert len(llm.calls) == 2  # no extra paid model calls on the retry


def test_verifier_trusts_the_chain_status_before_any_paid_call(tmp_path):
    chain, llm = chain_with("Submitted", "subId", [3]), FakeLLM()
    chain.statuses = {3: "Reported"}  # e.g. reported just before a crash, gateway not caught up
    verifier.run(chain, Jobs(str(tmp_path / "v.db")), gw=FakeGW(), embed=embed, llm=llm,
                 upload_json=uploads()[1], start_block=0, once=True)
    assert llm.calls == [] and chain.sent == []


def test_failed_post_is_resent_without_paying_for_the_model_again(tmp_path):
    clock = {"t": 0}
    chain, llm = chain_with("Submitted", "subId", [1]), FakeLLM(OK)
    j = Jobs(str(tmp_path / "v.db"), now=lambda: clock["t"])
    real_send, tries = chain.send, {"n": 0}

    def flaky_send(*args):
        tries["n"] += 1
        if tries["n"] == 1:
            raise RuntimeError("nonce too low")
        real_send(*args)

    chain.send = flaky_send
    for _ in range(2):
        verifier.run(chain, j, gw=FakeGW(nodes=[node1]), embed=embed, llm=llm, upload_json=uploads()[1],
                     start_block=0, once=True)
        clock["t"] += 60
    assert len(llm.calls) == 1 and [s[1] for s in chain.sent] == ["postReport"] and j.status(1)["status"] == "done"


def test_verdict_receipt_points_at_the_attempt_that_produced_the_verdict():
    r = verify(7, gw=FakeGW(nodes=[node1]), embed=embed, llm=FakeLLM("prose", OK), upload_json=uploads()[1])
    assert r["report"]["receipts"] == [root(1), root(2)] and r["report"]["verdict_receipt"] == root(2)
    r = verify(7, gw=FakeGW(nodes=[node1]), embed=embed, llm=FakeLLM("prose", "prose"), upload_json=uploads()[1])
    assert r["report"]["verdict_receipt"] is None


def test_existing_topic_without_a_summary_is_still_judged_as_existing():
    gw = FakeGW(nodes=[node1])
    gw.c["topic"] = None  # curator hasn't written topic metadata yet
    llm = FakeLLM(OK)
    verify(7, gw=gw, embed=embed, llm=llm, upload_json=uploads()[1])
    sent = json.loads(llm.calls[0][0][1]["content"])
    assert sent["topic"] == {"title": None, "description": None} and sent["closest_nodes"] == ["Coalitions"]
