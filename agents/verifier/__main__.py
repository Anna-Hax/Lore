"""Run the verifier: `uv run python -m verifier`."""

import logging
import os

import runtime
import shared
from jobs import Jobs
from verifier.agent import run

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    key = shared.deployment_key(int(os.environ.get("LORE_CHAIN_ID", 16602)))
    r = runtime.build("LORE_VERIFIER_KEY", Jobs(os.environ.get("LORE_JOBS_DB", "verifier-jobs.db"), deployment=key))
    embed = r["embed"]  # private, signature-checked 0G embeddings, cached per text
    run(r["chain"], r["jobs"], gw=r["gw"], embed=embed, llm=r["llm"], upload_json=r["upload_json"], start_block=r["start_block"])
