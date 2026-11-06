"""Run the gateway: `uv run python -m gateway`.

Env: LORE_CHAIN_ID (default 16602, P2's Galileo deployment), LORE_RPC (optional override),
LORE_GATEWAY_KEY (gateway wallet: holds LEAK_DETECTOR and REGISTRAR, pays finalize and registration gas),
WORLD_APP_ID, WORLD_RP_ID, WORLD_RP_SIGNING_KEY, WORLD_ACTION, WORLD_IDKIT_MODULE (see gateway/worldid.py),
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
from gateway.db import bind_deployment, connect
from gateway.worldid import WorldID


def main():
    from lore_shared import crypto, leak, storage, watermark

    content = SimpleNamespace(
        content_hash=crypto.content_hash, encrypt_node=lambda text, _content_hash: crypto.encrypt_node(text),
        decrypt_node=crypto.decrypt_node, watermark=watermark.watermark,
        validate_plaintext=watermark.validate_plaintext,
    )
    chain_id = int(os.environ.get("LORE_CHAIN_ID", 16602))
    dep = shared.deployment(chain_id)
    chain = Chain.for_chain(chain_id, os.environ["LORE_GATEWAY_KEY"], os.environ.get("LORE_RPC"))
    db_path = os.environ.get("LORE_DB", "gateway.db")
    bind_deployment(connect(db_path), shared.deployment_key(chain_id))  # refuse a db from another deployment

    threading.Thread(
        target=worker.run, args=(db_path, chain, storage, leak.best_match, dep["deployBlock"]), daemon=True
    ).start()
    world = WorldID(os.environ["WORLD_APP_ID"], os.environ["WORLD_RP_ID"], os.environ.get("WORLD_ACTION", "lore-person"),
                    os.environ.get("WORLD_RP_SIGNING_KEY"), os.environ.get("WORLD_IDKIT_MODULE"))
    app = create_app(db_path, chain, content, storage, world=world)
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("LORE_PORT", 8080)))


if __name__ == "__main__":
    main()
