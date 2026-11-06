"""Wires the verifier and curator to the real world from env vars.

Env: LORE_CHAIN_ID (default 16602), LORE_RPC (optional override), LORE_GATEWAY_URL, ZG_API_KEY (a trust_mode=private key),
ZG_MODEL (a TeeML model), plus the agent's role key (LORE_VERIFIER_KEY / LORE_CURATOR_KEY).
"""

import json
import os

import shared
import zg
from chain import Chain
from gwclient import Gateway


def provider_info(provider: str) -> tuple[str, str]:
    # ponytail: blocked on spike S q2 (which 0G contract/method returns a provider's url + teeSignerAddress).
    raise NotImplementedError("provider lookup pending spike S question 2")


def embed(text: str) -> list[float]:
    # ponytail: blocked on spike S q4 (TeeML embedding model on the router, else a local model).
    raise NotImplementedError("embedding model pending spike S question 4")


def upload_json(obj: dict) -> str:
    from lore_shared import storage  # ponytail: P3's library

    return storage.upload(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())


def build(key_env: str) -> dict:
    chain_id = int(os.environ.get("LORE_CHAIN_ID", 16602))
    dep = shared.deployment(chain_id)
    key = os.environ[key_env]
    model, api_key = os.environ["ZG_MODEL"], os.environ["ZG_API_KEY"]
    return {
        "chain": Chain.for_chain(chain_id, key, os.environ.get("LORE_RPC")),
        "gw": Gateway(os.environ["LORE_GATEWAY_URL"], key),
        "llm": lambda messages, version: zg.call(
            model, messages, prompt_version=version, api_key=api_key, provider_info=provider_info
        ),
        "upload_json": upload_json,
        "start_block": dep["deployBlock"],
    }
