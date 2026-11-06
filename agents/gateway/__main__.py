"""Run the gateway: `uv run python -m gateway`.

Env: LORE_CHAIN_ID (default 16602, P2's Galileo deployment), LORE_RPC (optional override),
LORE_GATEWAY_KEY (gateway wallet, holds LEAK_DETECTOR and pays finalize gas),
LORE_DB (sqlite path), LORE_PORT, plus whatever P3's lore_shared needs (MASTER_KEY, WM_SECRET, ...).
"""

import os
import threading
from types import SimpleNamespace

import uvicorn

import shared
from chain import Chain
from gateway import worker
from gateway.app import create_app


def main():
    # ponytail: P3's libraries; these imports fail until lore_shared exists.
    from lore_shared import crypto, leak, storage, watermark

    content = SimpleNamespace(
        content_hash=crypto.content_hash, encrypt_node=crypto.encrypt_node,
        decrypt_node=crypto.decrypt_node, watermark=watermark.watermark,
    )
    chain_id = int(os.environ.get("LORE_CHAIN_ID", 16602))
    dep = shared.deployment(chain_id)
    chain = Chain.for_chain(chain_id, os.environ["LORE_GATEWAY_KEY"], os.environ.get("LORE_RPC"))
    db_path = os.environ.get("LORE_DB", "gateway.db")

    threading.Thread(
        target=worker.run, args=(db_path, chain, storage, leak.best_match, dep["deployBlock"]), daemon=True
    ).start()
    uvicorn.run(create_app(db_path, chain, content, storage), host="0.0.0.0", port=int(os.environ.get("LORE_PORT", 8080)))


if __name__ == "__main__":
    main()
