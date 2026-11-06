"""Live storage spike: synthetic encrypted bytes only; requires a funded wallet."""

import json
import secrets
import time

from lore_shared.crypto import content_hash, decrypt_node, encrypt_node
from lore_shared.storage import download, upload


def run() -> dict:
    text = "Lore synthetic storage probe. No user research or credentials."
    key = secrets.token_bytes(32)
    blob = encrypt_node(text, master_key=key)
    start = time.monotonic()
    root = upload(blob)
    uploaded = time.monotonic()
    restored = download(root)
    finished = time.monotonic()
    if restored != blob or decrypt_node(restored, content_hash(text), master_key=key) != text:
        raise ValueError("storage round trip differs from uploaded content")
    return {"root": root, "bytes": len(blob), "upload_seconds": uploaded - start, "download_seconds": finished - uploaded, "roundtrip_passed": True}


if __name__ == "__main__":
    try:
        result = run()
    except Exception as error:
        print(json.dumps({"roundtrip_passed": False, "error_type": type(error).__name__}))
        raise SystemExit(2) from None
    print(json.dumps(result, indent=2))
