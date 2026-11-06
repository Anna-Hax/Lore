"""Persistent work queue for the verifier and curator.

Survives restarts: the chain cursor and every job's status live in sqlite, so a
restart neither re-processes finished work nor loses pending work. Logs are read
in bounded batches so a long-running chain never exceeds an RPC's range limit.

Failure handling, because a dead Submitted job leaves a user's stake locked:
- NotReady and transient errors (network, RPC, receipt timeout, no private 0G provider)
  are retried on the next pass and never count as an attempt.
- Other errors back off exponentially (30 s doubling, capped at 1 h); after MAX_ATTEMPTS
  (about 6 hours of retrying) the job is marked dead for an operator:
      uv run python -m jobs list verifier-jobs.db
      uv run python -m jobs requeue verifier-jobs.db [job_id ...]
"""

import logging
import sqlite3
import sys
import time

import httpx
import requests
from web3.exceptions import TimeExhausted

import zg

MAX_ATTEMPTS = 12
TRANSIENT = (httpx.TransportError, requests.ConnectionError, requests.Timeout, TimeExhausted, zg.ZGUnavailable)
log = logging.getLogger("lore.jobs")


class Skip(Exception):
    """Nothing to do for this item (already handled elsewhere); mark it done without retrying."""


class NotReady(Exception):
    """Try again later without counting an attempt (e.g. the gateway hasn't indexed it yet)."""


def backoff(attempts: int) -> int:
    return min(3600, 30 * 2 ** (attempts - 1))


class Jobs:
    def __init__(self, path: str, now=time.time):
        self.now = now
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS cursor (k TEXT PRIMARY KEY, block INT);
            CREATE TABLE IF NOT EXISTS jobs (id INT PRIMARY KEY, block INT, status TEXT DEFAULT 'pending',
                                             attempts INT DEFAULT 0, next_try INT DEFAULT 0, error TEXT);
        """)

    def pull(self, chain, event: str, key: str, start_block: int, batch: int = 2000) -> None:
        """Queue every `event` in the next batch of blocks, keyed by args[key]."""
        row = self.db.execute("SELECT block FROM cursor WHERE k='block'").fetchone()
        frm = (row[0] + 1) if row else start_block
        to = min(chain.latest(), frm + batch - 1)
        if frm > to:
            return
        with self.db:
            for block, _, _, a, _ in chain.logs(frm, to, only={event}):
                self.db.execute("INSERT OR IGNORE INTO jobs (id, block) VALUES (?, ?)", (a[key], block))
            self.db.execute("INSERT OR REPLACE INTO cursor VALUES ('block', ?)", (to,))

    def pending(self) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT id, block FROM jobs WHERE status='pending' AND next_try <= ? ORDER BY id", (int(self.now()),)
        ).fetchall()

    def done(self, job_id: int) -> None:
        with self.db:
            self.db.execute("UPDATE jobs SET status='done', error=NULL WHERE id=?", (job_id,))

    def failed(self, job_id: int, error: str) -> None:
        with self.db:
            attempts = self.db.execute(
                "UPDATE jobs SET attempts=attempts+1, error=? WHERE id=? RETURNING attempts", (error[:500], job_id)
            ).fetchone()[0]
            self.db.execute("UPDATE jobs SET next_try=?, status=? WHERE id=?",
                            (int(self.now()) + backoff(attempts), "dead" if attempts >= MAX_ATTEMPTS else "pending", job_id))

    def requeue(self, ids: list[int] | None = None) -> int:
        """Give dead jobs (all, or these ids) a fresh set of attempts. Returns how many were requeued."""
        with self.db:
            q = "UPDATE jobs SET status='pending', attempts=0, next_try=0 WHERE status='dead'"
            if ids:
                q += f" AND id IN ({','.join('?' * len(ids))})"
            return self.db.execute(q, ids or []).rowcount

    def status(self, job_id: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def loop(jobs: Jobs, chain, *, event: str, key: str, start_block: int, handle, every: int = 10, once: bool = False):
    """Pull new events, then run `handle(id, block)` on each due job.

    handle raises Skip (done, nothing to do), NotReady or a TRANSIENT error (retry next pass, free),
    or anything else (counts an attempt, then backs off).
    """
    while True:
        try:
            jobs.pull(chain, event, key, start_block)
            for j in jobs.pending():
                try:
                    handle(j["id"], j["block"])
                    jobs.done(j["id"])
                except Skip:
                    jobs.done(j["id"])
                except (NotReady, *TRANSIENT) as e:
                    log.info("%s %s not ready: %s", event, j["id"], e)
                except Exception as e:
                    log.exception("%s %s failed", event, j["id"])
                    jobs.failed(j["id"], repr(e))
        except Exception:
            log.exception("%s loop failed; retrying", event)
        if once:
            return
        time.sleep(every)


if __name__ == "__main__":
    cmd, path, *ids = sys.argv[1:] or ["help", ""]
    if cmd == "list":
        for r in Jobs(path).db.execute("SELECT * FROM jobs WHERE status != 'done' ORDER BY id"):
            print(dict(r))
    elif cmd == "requeue":
        print("requeued", Jobs(path).requeue([int(i) for i in ids] or None))
    else:
        print(__doc__)
