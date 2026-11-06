"""Run the curator: `uv run python -m curator`."""

import logging

import os

import runtime
import shared
from curator.agent import run
from jobs import Jobs

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    key = shared.deployment_key(int(os.environ.get("LORE_CHAIN_ID", 16602)))
    r = runtime.build("LORE_CURATOR_KEY", Jobs(os.environ.get("LORE_JOBS_DB", "curator-jobs.db"), deployment=key))
    run(r["chain"], r["jobs"], gw=r["gw"], llm=r["llm"], upload_json=r["upload_json"], start_block=r["start_block"])
