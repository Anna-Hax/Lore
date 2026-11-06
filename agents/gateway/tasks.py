"""Vote eligibility, the vote-before-submit gate, and what the finalizer may finalize.

The chain is the authority: P2's Submissions.canVote / canFinalize decide. The indexed
rows only narrow down which submissions are worth asking about, so we never send an
RPC per historical submission.
"""


def person_of(db, addr: str) -> str | None:
    row = db.execute("SELECT person FROM persons WHERE agent=?", (addr.lower(),)).fetchone()
    return row["person"] if row else None


def can_vote(db, chain, sub_id: int, addr: str) -> bool:
    """One vote per person: a vote by any of this person's agents counts, and none on their own submission."""
    addr = addr.lower()
    s = db.execute("SELECT status, topic_id, submitter FROM submissions WHERE id=?", (sub_id,)).fetchone()
    if not s or s["status"] != "Reported" or s["topic_id"] == 0:
        return False
    person = person_of(db, addr)
    if person and (person == person_of(db, s["submitter"])
                   or db.execute("SELECT 1 FROM votes WHERE sub_id=? AND person=?", (sub_id, person)).fetchone()):
        return False
    return chain.can_vote(sub_id, addr)  # live on-chain check: person, window, contributor-since, not voted


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
