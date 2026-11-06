"""Wires the verifier and curator to the real world from env vars.

Env: LORE_CHAIN_ID (default 16602), LORE_RPC (optional override), LORE_GATEWAY_URL, ZG_API_KEY (a trust_mode=private key),
ZG_MODEL (a TeeML model, e.g. glm-5.3), ZG_PROVIDER_CHAIN_ID (default 16661), plus the agent's role key (LORE_VERIFIER_KEY / LORE_CURATOR_KEY).
"""

import os

from lore_shared import storage
from lore_shared.canonical import canonical_json

import shared
import zg
from chain import Chain
from gwclient import Gateway
from zg.providers import Providers


def embed(text: str) -> list[float]:
    # ponytail: spike S4 picked qwen3-embedding-8b (TeeML on the router). Calling it privately and verified
    # needs a Router key to confirm the embeddings response and signature shape (spike S1).
    raise NotImplementedError("embeddings pending spike S1 (model: qwen3-embedding-8b)")


def upload_json(obj: dict) -> str:
    return storage.upload(canonical_json(obj).encode())


def build(key_env: str, jobs) -> dict:
    """jobs: the agent's jobs.Jobs; its PaidCache makes every 0G call pay at most once."""
    chain_id = int(os.environ.get("LORE_CHAIN_ID", 16602))
    dep = shared.deployment(chain_id)
    key = os.environ[key_env]
    model, api_key = os.environ["ZG_MODEL"], os.environ["ZG_API_KEY"]
    # Spike S2: the Router's providers are on 0G mainnet, so their records are read there.
    provider_info = Providers(int(os.environ.get("ZG_PROVIDER_CHAIN_ID", 16661)))
    return {
        "chain": Chain.for_chain(chain_id, key, os.environ.get("LORE_RPC")),
        "gw": Gateway(os.environ["LORE_GATEWAY_URL"], key),
        "llm": lambda messages, version: zg.call(
            model, messages, prompt_version=version, api_key=api_key, provider_info=provider_info, cache=jobs.paid
        ),
        "jobs": jobs,
        "upload_json": upload_json,
        "start_block": dep["deployBlock"],
    }
