"""Run the verifier: `uv run python -m verifier`."""

import logging
from functools import lru_cache

import os

import runtime
from jobs import Jobs
from verifier.agent import run

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    r = runtime.build("LORE_VERIFIER_KEY")
    # ponytail: in-memory embedding cache; persist it in sqlite if restarts get slow.
    embed = lru_cache(maxsize=10_000)(lambda t: tuple(runtime.embed(t)))
    run(r["chain"], Jobs(os.environ.get("LORE_JOBS_DB", "verifier-jobs.db")), gw=r["gw"], embed=embed, llm=r["llm"], upload_json=r["upload_json"], start_block=r["start_block"])
