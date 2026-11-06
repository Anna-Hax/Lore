"""Background loop: index the chain, fill in metadata, match leaks, finalize."""

import json
import logging
import time

from consts import MIN_LEAK_SCORE_BPS
from gateway import tasks
from gateway.db import connect, synced_block
from gateway.indexer import apply

log = logging.getLogger("lore.gateway")


def sync(db, chain, start_block: int, batch: int = 2000) -> int:
    """Index the next batch of blocks. Returns the last block indexed."""
    frm = max(synced_block(db) + 1, start_block)
    to = min(chain.latest(), frm + batch - 1)
    if frm > to:
        return to
    for block, idx, ev, args, ts in chain.logs(frm, to):
        with db:
            apply(db, ev, args, block, idx, ts)
    with db:
        db.execute("INSERT OR REPLACE INTO cursor VALUES ('block', ?)", (to,))
    return to


def fill_meta(db, storage) -> None:
    """Fetch metadata JSON for every node/topic whose on-chain metaHash we haven't loaded yet.

    ponytail: assumes the on-chain metaHash IS the 0G Storage root of the JSON (proposed §3 change).
    """
    for table in ("nodes", "topics"):
        for r in db.execute(f"SELECT id, meta_hash FROM {table} WHERE meta_hash IS NOT NULL AND meta_json IS NULL").fetchall():
            try:
                raw = storage.download(r["meta_hash"])
                json.loads(raw)
            except Exception as e:
                log.warning("meta %s %s not loaded yet: %s", table, r["id"], e)
                continue
            with db:
                db.execute(f"UPDATE {table} SET meta_json=? WHERE id=? AND meta_hash=?", (raw.decode(), r["id"], r["meta_hash"]))


def candidates_for(db, topic_id: int) -> list[tuple[str, int]]:
    """Every (wallet, mark_id) that got a watermarked copy of this topic's text.

    Buyers x node ids, plus voters x -sub_id (voter copies use negative ids so they never collide with nodes).
    """
    buyers = [b[0] for b in db.execute("SELECT wallet FROM deliveries WHERE topic_id=?", (topic_id,))]
    nodes = [n[0] for n in db.execute("SELECT id FROM nodes WHERE topic_id=?", (topic_id,))]
    voters = db.execute(
        "SELECT v.wallet, v.sub_id FROM vote_views v JOIN submissions s ON s.id=v.sub_id WHERE s.topic_id=?", (topic_id,)
    ).fetchall()
    return [(w, n) for w in buyers for n in nodes] + [(w, -s) for w, s in voters]


def match_leaks(db, chain, best_match, tried: set) -> None:
    """For each unmatched leak report with posted evidence, find the most likely buyer and record it on-chain."""
    rows = db.execute(
        "SELECT r.id, r.topic_id, e.text FROM reports r JOIN evidence e ON e.hash=r.evidence_hash"
        " WHERE r.matched_wallet IS NULL"
    ).fetchall()
    for r in rows:
        if r["id"] in tried:
            continue
        tried.add(r["id"])
        candidates = candidates_for(db, r["topic_id"])
        if not candidates:
            continue
        wallet, score = best_match(r["text"], candidates)
        if score < MIN_LEAK_SCORE_BPS:  # no real watermark match: never accuse a buyer or voter on-chain
            log.info("leak report %s: best score %s below %s, not recorded", r["id"], score, MIN_LEAK_SCORE_BPS)
            continue
        try:
            chain.send("Reports", "recordMatch", r["id"], chain.w3.to_checksum_address(wallet), score)
        except Exception as e:
            log.error("recordMatch for report %s failed: %s", r["id"], e)
            tried.discard(r["id"])


def finalize_due(db, chain) -> None:
    for sid in tasks.finalizable(db, chain):  # only what canFinalize approves: no wasted reverting txs
        try:
            chain.send("Submissions", "finalize", sid)
        except Exception as e:  # e.g. already finalized by someone else; the next sync catches up
            log.warning("finalize %s failed: %s", sid, e)


def run(db_path: str, chain, storage, best_match, start_block: int, every: int = 15) -> None:
    db = connect(db_path)  # opened on this thread: sqlite connections stay with the thread that uses them
    tried, last_finalize = set(), 0
    while True:
        try:
            sync(db, chain, start_block)
            fill_meta(db, storage)
            match_leaks(db, chain, best_match, tried)
            if time.time() - last_finalize >= 60:
                finalize_due(db, chain)
                last_finalize = time.time()
        except Exception:
            log.exception("worker loop failed; retrying")
        time.sleep(every)
