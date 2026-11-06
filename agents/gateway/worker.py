"""Background loop: index the chain, fill in metadata, match leaks, finalize."""

import json
import logging
import time

from gateway import tasks
from gateway.db import connect, synced_block
from gateway.indexer import apply

log = logging.getLogger("lore.gateway")
SYNC_EVERY = 3     # seconds between index passes: keeps the gateway within a few blocks of the chain
SLOW_EVERY = 15    # metadata downloads and leak matching
FINALIZE_EVERY = 60


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


def candidates_for(db, topic_id: int) -> list[tuple[str, str]]:
    """Every (wallet, ref) that received a watermarked copy of this topic: buyers' node copies and voters' tasks."""
    return [(r[0], r[1]) for r in db.execute("SELECT wallet, ref FROM deliveries WHERE topic_id=? ORDER BY wallet, ref",
                                             (topic_id,))]


def match_leaks(db, chain, best_match, tried: set) -> None:
    """For each unmatched leak report with posted evidence, find whose copy leaked and record it on-chain.

    best_match (lore_shared.leak) names someone only on an exact watermark match; otherwise it returns
    (None, None, 0) and the report stays unmatched. Never fall back to a nearby wallet.
    """
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
        wallet, ref, score = best_match(r["text"], candidates)
        if wallet is None:
            log.info("leak report %s: no exact watermark match, left unmatched", r["id"])
            continue
        try:
            chain.send("Reports", "recordMatch", r["id"], chain.w3.to_checksum_address(wallet), score)
            with db:  # off-chain diagnostic: which copy it was
                db.execute("UPDATE reports SET matched_ref=? WHERE id=?", (ref, r["id"]))
        except Exception as e:
            log.error("recordMatch for report %s failed: %s", r["id"], e)
            tried.discard(r["id"])


def finalize_due(db, chain) -> None:
    for sid in tasks.finalizable(db, chain):  # only what canFinalize approves: no wasted reverting txs
        try:
            chain.send("Submissions", "finalize", sid)
        except Exception as e:  # e.g. already finalized by someone else; the next sync catches up
            log.warning("finalize %s failed: %s", sid, e)


def run(db_path: str, chain, storage, best_match, start_block: int) -> None:
    """Index on a fast loop; do slow work (downloads, transactions) on another thread so it never stalls indexing.

    The vote-before-submit gate refuses lore_submit when indexing falls more than MAX_LAG blocks behind, so
    indexing must never wait on a storage download or a finalize receipt.
    """
    import threading

    threading.Thread(target=_slow_loop, args=(db_path, chain, storage, best_match), daemon=True).start()
    db = connect(db_path)  # each thread opens its own connection
    while True:
        try:
            while sync(db, chain, start_block) < chain.latest():  # catch up fully, then rest
                pass
        except Exception:
            log.exception("index loop failed; retrying")
        time.sleep(SYNC_EVERY)


def _slow_loop(db_path: str, chain, storage, best_match) -> None:
    db = connect(db_path)
    tried, last_finalize = set(), 0.0
    while True:
        try:
            fill_meta(db, storage)
            match_leaks(db, chain, best_match, tried)
            if time.time() - last_finalize >= FINALIZE_EVERY:
                finalize_due(db, chain)
                last_finalize = time.time()
        except Exception:
            log.exception("slow loop failed; retrying")
        time.sleep(SLOW_EVERY)
