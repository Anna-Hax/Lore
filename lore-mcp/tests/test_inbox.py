import asyncio

from lore_mcp import server
from lore_mcp.inbox import Inbox

TASK = {"sub_id": 2, "topic_id": 1, "deadline": 99}


def feed(*pages):
    """A fake gateway /inbox that returns these pages in order and records the since_node it was asked for."""
    asked, pages = [], list(pages)

    def fetch(since):
        asked.append(since)
        return pages.pop(0)

    return fetch, asked


def page(vote_tasks=(), subs=(), nodes=(), latest=0):
    return {"vote_tasks": list(vote_tasks), "submissions": list(subs), "new_nodes": list(nodes), "latest_node": latest}


def test_first_run_is_quiet_except_vote_tasks(tmp_path):
    fetch, _ = feed(page([TASK], [{"sub_id": 1, "topic_id": 0, "status": "Accepted", "node_id": 1}],
                         [{"node_id": 1, "topic_id": 1, "title": "Old"}], latest=1))
    ib = Inbox(fetch, tmp_path / "s.json")
    ib.refresh()
    assert ib.take() == {"vote_tasks": [TASK], "updates": []}
    assert "1 open vote task " in ib.notice()


def test_later_polls_report_status_changes_and_new_nodes_then_clear_them(tmp_path):
    sub = {"sub_id": 5, "topic_id": 1, "node_id": None}
    fetch, asked = feed(
        page(subs=[{**sub, "status": "Pending"}], latest=3),
        page(subs=[{**sub, "status": "Reported"}], latest=3),
        page(subs=[{**sub, "status": "Accepted", "node_id": 4}], nodes=[{"node_id": 4, "topic_id": 1, "title": "Turnout"}], latest=4),
    )
    ib = Inbox(fetch, tmp_path / "s.json")
    ib.refresh()
    ib.refresh()
    ib.refresh()
    assert asked == [0, 3, 3]
    assert ib.take()["updates"] == [
        "Your submission #5 is now Reported.",
        "Your submission #5 is now Accepted as node #4.",
        "New node #4 in topic 1: Turnout",
    ]
    assert ib.take()["updates"] == [] and ib.notice() is None


def test_state_persists_across_sessions(tmp_path):
    fetch, _ = feed(page(latest=7))
    Inbox(fetch, tmp_path / "s.json").refresh()
    fetch2, asked = feed(page(nodes=[{"node_id": 8, "topic_id": 1, "title": "New"}], latest=8))
    ib = Inbox(fetch2, tmp_path / "s.json")
    ib.refresh()
    assert asked == [7] and ib.take()["updates"] == ["New node #8 in topic 1: New"]  # new since last session


def test_tool_results_carry_the_notice_and_keep_their_input_schema(monkeypatch):
    monkeypatch.setattr(server.inbox, "vote_tasks", [TASK])
    monkeypatch.setattr(server.lore, "gw", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(server.lore, "stake", lambda: 10_000000)
    out = server.lore_submit("research", 1)  # no confirm: returns the stake warning without calling anything
    assert out.endswith("Call lore_inbox to see them.]")
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    assert set(tools["lore_submit"].input_schema["properties"]) == {"text", "topic_id", "confirm"}
    assert "lore_inbox" in tools


def test_overlapping_refreshes_never_duplicate_updates(tmp_path):
    import threading
    import time

    base = page(latest=1)
    newer = page(nodes=[{"node_id": 2, "topic_id": 1, "title": "A"}, {"node_id": 3, "topic_id": 1, "title": "B"}], latest=3)
    calls = {"n": 0}

    def slow_fetch(since):
        calls["n"] += 1
        if calls["n"] == 1:
            return base
        time.sleep(0.05)  # both threads would read since_node=1 here without the refresh lock
        return newer if since < 3 else page(latest=3)

    ib = Inbox(slow_fetch, tmp_path / "s.json")
    ib.refresh()
    threads = [threading.Thread(target=ib.refresh) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert ib.take()["updates"] == ["New node #2 in topic 1: A", "New node #3 in topic 1: B"]
