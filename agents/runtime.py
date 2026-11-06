"""Wires the verifier and curator to the real world from env vars.

Env: LORE_CHAIN_ID (default 16602), LORE_RPC (optional override), LORE_GATEWAY_URL, LORE_SERVICE_TOKEN, ZG_API_KEY (a trust_mode=private key),
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


def embed_with(api_key: str, provider_info, model: str | None = None):
    """Private, signature-checked embeddings on the 0G Router (spike S4: qwen3-embedding-8b, TeeML).

    Cached by exact text for the life of the process: the verifier re-embeds the same topic nodes for every submission.
    """
    model = model or os.environ.get("ZG_EMBED_MODEL", "qwen3-embedding-8b")
    cache: dict[str, list[float]] = {}

    def embed(text: str) -> list[float]:
        if text not in cache:
            cache[text] = zg.embed(text, model=model, api_key=api_key, provider_info=provider_info)
        return cache[text]

    return embed


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
        "gw": Gateway(os.environ["LORE_GATEWAY_URL"], os.environ["LORE_SERVICE_TOKEN"]),
        "llm": lambda messages, version: zg.call(
            model, messages, prompt_version=version, api_key=api_key, provider_info=provider_info, cache=jobs.paid
        ),
        "embed": embed_with(api_key, provider_info),
        "jobs": jobs,
        "upload_json": upload_json,
        "start_block": dep["deployBlock"],
    }
