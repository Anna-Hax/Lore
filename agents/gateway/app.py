"""Gateway HTTP API (BUILD_PLAN §3.4).

Plaintext only ever leaves through endpoints that just passed a live on-chain
check: access (buyers), vote eligibility (voters) or role (verifier, curator).

`content` and `storage` are P3's libraries (lore_shared.crypto/watermark and
lore_shared.storage). The gateway only needs:
    content.content_hash(text) -> "0x.."
    content.encrypt_node(text, content_hash) -> bytes
    content.decrypt_node(blob, content_hash) -> str
    content.watermark(text, wallet, mark_id) -> str   (mark_id: node id, or -sub_id for a voter's copy)
    storage.upload(data: bytes) -> "0x.." root
    storage.download(root) -> bytes
"""

import json
import time

from eth_utils import keccak
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from consts import MAX_CHARS

INGEST_TTL = 600  # an ingest must be submitted on-chain within 10 min, so it can't skip votes assigned later
MAX_LAG = 20      # blocks (~10 s on 0G): refuse ingests while the indexer is behind, or the vote gate is blind
from gateway import auth, tasks
from gateway.db import connect, synced_block


class NonceIn(BaseModel):
    address: str


class VerifyIn(BaseModel):
    address: str
    message: str
    signature: str


class IngestIn(BaseModel):
    text: str = Field(max_length=MAX_CHARS)  # every ingest is a paid upload; cap it
    topic_id: int = 0  # 0 = new topic


class LeakIn(BaseModel):
    topic_id: int
    text: str = Field(max_length=MAX_CHARS)


def create_app(db_path: str, chain, content, storage, now=lambda: int(time.time())) -> FastAPI:
    app = FastAPI(title="Lore gateway")

    def db():
        conn = connect(db_path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # scope="function": commit before the response is sent, so a failed write is a 500, never a silent 200.
    DB = Depends(db, scope="function")

    def gated(conn, s) -> bool:
        """True iff this on-chain submission is the content its own submitter ingested through us, recently.

        Anyone can copy a (content_hash, storage_root) pair from a failed or front-run tx and submit it; without
        this check the gateway would decrypt someone else's text for the copier's accomplices.
        """
        ing = conn.execute("SELECT * FROM ingests WHERE content_hash=?", (s["content_hash"],)).fetchone()
        return (bool(ing) and ing["storage_root"] == s["storage_root"] and ing["caller"] == s["submitter"]
                and s["submitted_at"] is not None and s["submitted_at"] - ing["ingested_at"] <= INGEST_TTL)

    def caller(authorization: str = Header(None), conn=DB) -> str:
        token = (authorization or "").removeprefix("Bearer ").strip()
        addr = auth.address_for(conn, token) if token else None
        if not addr:
            raise HTTPException(401, "sign in first: POST /auth/nonce then /auth/verify")
        return addr

    def lore_role(addr: str = Depends(caller)) -> str:
        if not (chain.has_role("VERIFIER", addr) or chain.has_role("CURATOR", addr)):
            raise HTTPException(403, "verifier or curator role required")
        return addr

    def plaintext(content_hash: str, root: str) -> str:
        return content.decrypt_node(storage.download(root), content_hash)

    def meta(raw):
        return json.loads(raw) if raw else None

    # --- auth ---
    @app.post("/auth/nonce")
    def nonce(body: NonceIn, conn=DB):
        return {"message": auth.new_message(conn, body.address)}

    @app.post("/auth/verify")
    def verify(body: VerifyIn, conn=DB):
        token = auth.verify(conn, body.address, body.message, body.signature)
        if not token:
            raise HTTPException(401, "bad or expired signature")
        return {"token": token}

    # --- public ---
    @app.get("/topics")
    def topics(conn=DB):
        rows = conn.execute(
            "SELECT t.id, t.meta_json, COUNT(n.id) AS n FROM topics t LEFT JOIN nodes n ON n.topic_id=t.id"
            " GROUP BY t.id ORDER BY t.id"
        )
        price = chain.topic_price()  # settable on-chain by ADMIN
        return [{"topic_id": r["id"], "meta": meta(r["meta_json"]), "node_count": r["n"], "price": price}
                for r in rows]

    @app.get("/topics/{tid}")
    def topic(tid: int, conn=DB):
        t = conn.execute("SELECT * FROM topics WHERE id=?", (tid,)).fetchone()
        if not t:
            raise HTTPException(404, "no such topic")
        nodes = conn.execute("SELECT id, contributor, meta_json FROM nodes WHERE topic_id=? ORDER BY id", (tid,)).fetchall()
        return {
            "topic_id": tid, "meta": meta(t["meta_json"]), "price": chain.topic_price(),
            "nodes": [{
                "node_id": n["id"], "contributor": n["contributor"], "meta": meta(n["meta_json"]),
                "parents": [e[0] for e in conn.execute("SELECT parent FROM edges WHERE child=?", (n["id"],))],
            } for n in nodes],
        }

    @app.get("/proofs/{root}")
    def proof(root: str):
        return json.loads(storage.download(root))

    # --- users ---
    @app.get("/vote-tasks")
    def vote_tasks(addr=Depends(caller), conn=DB):
        return tasks.open_vote_tasks(conn, chain, addr, now())

    @app.get("/vote-tasks/{sid}")
    def vote_task(sid: int, addr=Depends(caller), conn=DB):
        if not tasks.can_vote(conn, chain, sid, addr):
            raise HTTPException(403, "not eligible to vote on this submission")
        s = conn.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()
        report = json.loads(storage.download(s["report_hash"]))
        # Voters get their own watermarked copy, so a leak from a vote task is traceable too. Content that its
        # submitter didn't ingest is never decrypted: it may be someone else's text (see gated()).
        text = (content.watermark(plaintext(s["content_hash"], s["storage_root"]), addr, -sid)
                if gated(conn, s) else None)
        parents = conn.execute(
            f"SELECT id, meta_json FROM nodes WHERE id IN ({','.join('?' * len(report['parents']))})",
            [p["node_id"] for p in report["parents"]],
        ).fetchall() if report["parents"] else []
        conn.execute("INSERT OR IGNORE INTO vote_views VALUES (?, ?)", (sid, addr))  # after the slow I/O
        return {
            "sub_id": sid, "topic_id": s["topic_id"], "text": text,
            "report": report, "receipts": report.get("receipts", []),
            "parents_meta": [{"node_id": p["id"], "meta": meta(p["meta_json"])} for p in parents],
        }

    @app.get("/inbox")
    def inbox(since_node: int = 0, addr=Depends(caller), conn=DB):
        """Everything new for the caller, in one poll: open vote tasks, their submissions' status,
        and nodes added (after `since_node`) to topics they bought or contributed to."""
        subs = conn.execute(
            "SELECT id, topic_id, status, node_id FROM submissions WHERE submitter=? ORDER BY id DESC LIMIT 50", (addr,)
        ).fetchall()
        nodes = conn.execute(
            "SELECT n.id, n.topic_id, n.meta_json FROM nodes n WHERE n.id > ? AND n.topic_id IN ("
            " SELECT topic_id FROM purchases WHERE buyer=? UNION SELECT topic_id FROM nodes WHERE contributor=?)"
            " ORDER BY n.id LIMIT 100", (since_node, addr, addr),
        ).fetchall()
        return {
            "vote_tasks": tasks.open_vote_tasks(conn, chain, addr, now()),
            "submissions": [{"sub_id": r["id"], "topic_id": r["topic_id"], "status": r["status"], "node_id": r["node_id"]}
                            for r in subs],
            "new_nodes": [{"node_id": r["id"], "topic_id": r["topic_id"], "title": (meta(r["meta_json"]) or {}).get("title")}
                          for r in nodes],
            "latest_node": conn.execute("SELECT COALESCE(MAX(id), 0) FROM nodes").fetchone()[0],
        }

    @app.post("/ingest")
    def ingest(body: IngestIn, addr=Depends(caller), conn=DB):
        if chain.latest() - synced_block(conn) > MAX_LAG:
            raise HTTPException(503, "Lore is catching up with the chain; try again in a few seconds")
        if tasks.open_vote_tasks(conn, chain, addr, now()):  # the vote-before-submit gate lives here, server side
            raise HTTPException(409, "finish your open vote tasks before submitting (GET /vote-tasks)")
        ch = content.content_hash(body.text)
        prior = conn.execute("SELECT * FROM ingests WHERE content_hash=?", (ch,)).fetchone()
        if prior:
            submitted = conn.execute("SELECT 1 FROM submissions WHERE content_hash=?", (ch,)).fetchone()
            if prior["caller"] == addr and not submitted:  # retry after a failed approve/submit: restart the clock
                conn.execute("UPDATE ingests SET ingested_at=?, topic_id=? WHERE content_hash=?", (now(), body.topic_id, ch))
                return {"content_hash": ch, "storage_root": prior["storage_root"]}
            raise HTTPException(409, "this exact text was already submitted")
        root = storage.upload(content.encrypt_node(body.text, ch))
        conn.execute("INSERT INTO ingests VALUES (?, ?, ?, ?, ?)", (ch, addr, root, body.topic_id, now()))
        return {"content_hash": ch, "storage_root": root}

    @app.get("/topics/{tid}/content")
    def read(tid: int, addr=Depends(caller), conn=DB):
        if not chain.has_access(tid, addr):  # live on-chain read, never cached
            raise HTTPException(403, "buy this topic first")
        nodes = conn.execute(
            "SELECT * FROM nodes WHERE topic_id=? AND storage_root IS NOT NULL ORDER BY id", (tid,)
        ).fetchall()
        out = [{
            "node_id": n["id"], "meta": meta(n["meta_json"]),
            "parents": [e[0] for e in conn.execute("SELECT parent FROM edges WHERE child=?", (n["id"],))],
            "text": content.watermark(plaintext(n["content_hash"], n["storage_root"]), addr, n["id"]),
        } for n in nodes]
        # Write last: the write lock is held only until the request commits, never during downloads.
        conn.execute("INSERT OR IGNORE INTO deliveries VALUES (?, ?)", (tid, addr))
        return {"nodes": out}

    @app.post("/leaks")
    def leak(body: LeakIn, addr=Depends(caller), conn=DB):
        h = "0x" + keccak(text=body.text).hex()
        conn.execute("INSERT OR IGNORE INTO evidence VALUES (?, ?, ?)", (h, body.topic_id, body.text))
        return {"evidence_hash": h}

    # --- Lore's own agents ---
    @app.get("/internal/plaintext/{kind}/{iid}")
    def internal_plaintext(kind: str, iid: int, _=Depends(lore_role), conn=DB):
        if kind == "node":
            n = conn.execute("SELECT * FROM nodes WHERE id=? AND storage_root IS NOT NULL", (iid,)).fetchone()
            if not n:
                raise HTTPException(404, "no such node")
            return {"topic_id": n["topic_id"], "ingested": True, "meta_hash": n["meta_hash"],
                    "synced_block": synced_block(conn), "text": plaintext(n["content_hash"], n["storage_root"])}
        if kind != "sub":
            raise HTTPException(404, "kind must be sub or node")
        s = conn.execute("SELECT * FROM submissions WHERE id=?", (iid,)).fetchone()
        if not s:
            raise HTTPException(404, "no such submission (not indexed yet?)")
        base = {"topic_id": s["topic_id"], "status": s["status"], "synced_block": synced_block(conn)}
        if not gated(conn, s):  # skipped the gate, someone else's content, or a stale ingest: never decrypted
            return {**base, "ingested": False, "text": None}
        return {**base, "ingested": True, "text": plaintext(s["content_hash"], s["storage_root"])}

    @app.get("/internal/candidates/{tid}")
    def candidates(tid: int, _=Depends(lore_role), conn=DB):
        nodes = conn.execute("SELECT * FROM nodes WHERE topic_id=? AND storage_root IS NOT NULL", (tid,)).fetchall()
        pending = [s for s in conn.execute(
            "SELECT * FROM submissions WHERE topic_id=? AND status IN ('Pending', 'Reported')", (tid,)
        ).fetchall() if gated(conn, s)]
        t = conn.execute("SELECT meta_json FROM topics WHERE id=?", (tid,)).fetchone()
        return {
            "synced_block": synced_block(conn),
            "topic": meta(t["meta_json"]) if t else None,
            "nodes": [{"node_id": n["id"], "meta": meta(n["meta_json"]),
                       "text": plaintext(n["content_hash"], n["storage_root"])} for n in nodes],
            "pending": [{"sub_id": s["id"], "text": plaintext(s["content_hash"], s["storage_root"])} for s in pending],
        }

    return app
