"""Vote eligibility, the vote-before-submit gate, and what the finalizer may finalize.

The chain is the authority: P2's Submissions.canVote / canFinalize decide. The indexed
rows only narrow down which submissions are worth asking about, so we never send an
RPC per historical submission.
"""


def can_vote(db, chain, sub_id: int, addr: str) -> bool:
    addr = addr.lower()
    s = db.execute("SELECT status, topic_id, submitter FROM submissions WHERE id=?", (sub_id,)).fetchone()
    if not s or s["status"] != "Reported" or s["topic_id"] == 0 or s["submitter"] == addr:
        return False
    if db.execute("SELECT 1 FROM votes WHERE sub_id=? AND voter=?", (sub_id, addr)).fetchone():
        return False
    return chain.can_vote(sub_id, addr)  # live on-chain check: window, contributor-since, not voted


def open_vote_tasks(db, chain, addr: str, now: int) -> list[dict]:
    window = chain.voting_window()  # settable on-chain by ADMIN, so read it rather than assume 24h
    rows = db.execute(
        "SELECT id, topic_id, reported_at FROM submissions"
        " WHERE status='Reported' AND topic_id != 0 AND reported_at > ? ORDER BY id",
        (now - window,),
    ).fetchall()
    return [
        {"sub_id": r["id"], "topic_id": r["topic_id"], "deadline": r["reported_at"] + window}
        for r in rows if can_vote(db, chain, r["id"], addr)
    ]


def finalizable(db, chain) -> list[int]:
    """Reported submissions the chain says can be finalized right now."""
    rows = db.execute("SELECT id FROM submissions WHERE status='Reported' ORDER BY id").fetchall()
    return [r["id"] for r in rows if chain.can_finalize(r["id"])]
