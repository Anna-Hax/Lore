"""Lore's curator (BUILD_PLAN §4 D): writes node and topic titles and descriptions.

Injected like the verifier: gw, llm (zg.call bound), upload_json.

The curator remembers every title/description it has written (`Memory`), so the
topic summary it writes for node N already includes node N-1 even when the
gateway hasn't indexed N-1's metadata yet.
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import zg
from jobs import NotReady, Skip, loop

NODE_V, TOPIC_V = "node_v1", "topic_v1"
PROMPTS = {v: (Path(__file__).parent / "prompts" / f"{v}.md").read_text() for v in (NODE_V, TOPIC_V)}
log = logging.getLogger("lore.curator")


class BadMeta(Exception):
    """The model's title/description broke the length rules twice."""


class Memory:
    """Titles/descriptions this curator wrote, per topic. Lives in the jobs sqlite file."""

    def __init__(self, db):
        self.db = db
        db.executescript("""
            CREATE TABLE IF NOT EXISTS node_meta (node_id INT PRIMARY KEY, topic_id INT, title TEXT, description TEXT);
            CREATE TABLE IF NOT EXISTS topic_meta (topic_id INT PRIMARY KEY, title TEXT, description TEXT);
            CREATE TABLE IF NOT EXISTS results (node_id INT PRIMARY KEY, topic_id INT, node_root TEXT,
                                                topic_root TEXT, node_sent INT DEFAULT 0, topic_sent INT DEFAULT 0);
        """)

    def result(self, node_id: int):
        return self.db.execute("SELECT * FROM results WHERE node_id=?", (node_id,)).fetchone()

    def record(self, node_id: int, topic_id: int, node_root: str, topic_root: str) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO results (node_id, topic_id, node_root, topic_root) VALUES (?, ?, ?, ?)",
                            (node_id, topic_id, node_root, topic_root))

    def sent(self, node_id: int, which: str) -> None:
        assert which in ("node_sent", "topic_sent")
        with self.db:
            self.db.execute(f"UPDATE results SET {which}=1 WHERE node_id=?", (node_id,))

    def nodes(self, topic_id: int) -> dict[int, dict]:
        rows = self.db.execute("SELECT * FROM node_meta WHERE topic_id=?", (topic_id,))
        return {r[0]: {"title": r[2], "description": r[3]} for r in rows}

    def topic(self, topic_id: int) -> dict | None:
        r = self.db.execute("SELECT title, description FROM topic_meta WHERE topic_id=?", (topic_id,)).fetchone()
        return {"title": r[0], "description": r[1]} if r else None

    def save(self, topic_id: int, node_id: int, node: dict, topic: dict) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO node_meta VALUES (?, ?, ?, ?)",
                            (node_id, topic_id, node["title"], node["description"]))
            self.db.execute("INSERT OR REPLACE INTO topic_meta VALUES (?, ?, ?)",
                            (topic_id, topic["title"], topic["description"]))


def _write(llm, version: str, payload: dict, upload_json) -> tuple[dict, str]:
    """One model call that must return a valid {title, description}. Retries once on bad output."""
    title = desc = ""
    for _ in range(2):
        out, receipt = llm([
            {"role": "system", "content": PROMPTS[version]},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ], version)
        try:
            m = zg.json_out(out)
            # Not stripped: what we publish must equal the signed output byte for byte, so proofs match.
            title, desc = str(m.get("title", "")), str(m.get("description", ""))
        except (ValueError, AttributeError):
            continue
        if 0 < len(title) <= 80 and 300 <= len(desc) <= 600:
            return {"title": title, "description": desc}, upload_json(receipt)
    raise BadMeta(f"{version}: title {len(title)} chars, description {len(desc)} chars")


def curate(node_id: int, *, gw, llm, upload_json, memory: Memory | None = None) -> dict:
    """Return {"node_root", "topic_root", "topic_id", "node_meta", "topic_meta"}."""
    p = gw.plaintext("node", node_id)
    topic_id = p["topic_id"]
    topic = gw.topic(topic_id)
    now = datetime.now(UTC).isoformat()

    # What we know about the topic: the gateway's view, overridden by anything we wrote ourselves.
    known = {n["node_id"]: {"title": n["meta"]["title"], "description": n["meta"]["description"]}
             for n in topic["nodes"] if n["meta"]}
    current = ({"title": topic["meta"]["title"], "description": topic["meta"]["description"]}
               if topic["meta"] else None)
    if memory:
        known |= memory.nodes(topic_id)
        current = memory.topic(topic_id) or current
    known.pop(node_id, None)

    m, receipt = _write(llm, NODE_V, {"topic": current, "research": p["text"]}, upload_json)
    node_meta = {"node_id": str(node_id), **m, "receipt": receipt, "created_at": now}

    nodes = [known[k] for k in sorted(known)] + [m]
    t, t_receipt = _write(llm, TOPIC_V, {"current": current, "nodes": nodes}, upload_json)
    count = len({n["node_id"] for n in topic["nodes"]} | set(known) | {node_id})
    topic_meta = {"topic_id": str(topic_id), **t, "node_count": count, "receipt": t_receipt, "created_at": now}

    if memory:
        memory.save(topic_id, node_id, m, t)
    return {"topic_id": topic_id, "node_meta": node_meta, "topic_meta": topic_meta,
            "node_root": upload_json(node_meta), "topic_root": upload_json(topic_meta)}


def run(chain, jobs, *, gw, llm, upload_json, start_block: int, every: int = 10, once: bool = False):
    """Curate every NodeAdded event. State lives in `jobs` (survives restarts)."""
    memory = Memory(jobs.db)
    root = lambda h: bytes.fromhex(h.removeprefix("0x"))  # noqa: E731

    def handle(node_id, block):
        r = memory.result(node_id)
        if r is None:  # not curated yet: write it (paid model calls happen only here, once)
            p = gw.plaintext("node", node_id)
            if p["synced_block"] < block:
                raise NotReady(f"gateway at block {p['synced_block']}, need {block}")
            if p["meta_hash"]:  # metadata exists but we have no record (job db lost): never pay twice
                raise Skip(f"node {node_id} already curated")
            out = curate(node_id, gw=gw, llm=llm, upload_json=upload_json, memory=memory)
            memory.record(node_id, out["topic_id"], out["node_root"], out["topic_root"])
            log.info("node %s curated: %s", node_id, out["node_meta"]["title"])
            r = memory.result(node_id)
        # Send whichever transaction hasn't landed yet, so a failed setTopicMeta is retried, not skipped.
        if not r["node_sent"]:
            chain.send("TopicGraph", "setNodeMeta", node_id, root(r["node_root"]))
            memory.sent(node_id, "node_sent")
        if not r["topic_sent"]:
            chain.send("TopicGraph", "setTopicMeta", r["topic_id"], root(r["topic_root"]))
            memory.sent(node_id, "topic_sent")

    loop(jobs, chain, event="NodeAdded", key="nodeId", start_block=start_block, handle=handle, every=every, once=once)
