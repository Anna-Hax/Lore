"""Collect the CLI's provider verification evidence and publish it to Storage.

Finds receipts through the gateway's sqlite index (read-only) and public /proofs.
This job does not call a model, copy prompts, or claim independent TEE validation.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
from urllib.request import urlopen

from lore_shared.canonical import canonical_json
from lore_shared.storage import upload


def receipt_roots(db_path: Path, fetch) -> list[str]:
    """Receipt roots from curator metadata and verifier reports."""
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        roots = {json.loads(raw).get("receipt") for table in ("nodes", "topics")
                 for (raw,) in db.execute(f"SELECT meta_json FROM {table} WHERE meta_json IS NOT NULL")}
        reports = [row[0] for row in db.execute("SELECT report_hash FROM submissions WHERE report_hash IS NOT NULL")]
    finally:
        db.close()
    for report in reports:
        roots.update(fetch(report).get("receipts", []))
    return sorted(root for root in roots if root)


def gateway_fetch(url: str):
    def fetch(root: str) -> dict:
        with urlopen(f"{url.rstrip('/')}/proofs/{root}", timeout=60) as response:
            return json.load(response)
    return fetch


def providers(receipts: list[dict]) -> list[str]:
    result = set()
    if not isinstance(receipts, list):
        raise ValueError("expected a receipt array")
    for receipt in receipts:
        if receipt.get("trust_mode") != "private" or receipt.get("tee_verified") is not True or receipt.get("signer_matches_onchain") is not True:
            raise ValueError("unverified receipt in provider inventory")
        address = receipt.get("provider", "")
        if not isinstance(address, str) or not re.fullmatch(r"0x[0-9a-fA-F]{40}", address):
            raise ValueError("invalid provider address")
        result.add(address.lower())
    return sorted(result)


def attest(receipts: list[dict], *, cli: str = "0g-compute-cli", publish=upload) -> list[dict]:
    results = []
    for provider in providers(receipts):
        try:
            process = subprocess.run(
                [cli, "inference", "verify", "--provider", provider],
                capture_output=True, text=True, timeout=180, check=False,
                env={name: os.environ[name] for name in ("PATH", "HOME") if name in os.environ},
            )
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError("provider attestation CLI failed or timed out") from None
        if process.returncode or not process.stdout.strip():
            raise RuntimeError("provider attestation failed; no evidence published")
        # Store only public CLI evidence, never the receipt's signed text/prompt.
        evidence = {"kind": "provider-cli-verification-output", "provider": provider,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "cli_exit_code": 0, "stdout": process.stdout}
        root = publish(canonical_json(evidence).encode("utf-8"))
        results.append({"provider": provider, "storage_root": root})
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--gateway", default="http://127.0.0.1:8080")
    parser.add_argument("--cli", default="0g-compute-cli")
    args = parser.parse_args()
    try:
        fetch = gateway_fetch(args.gateway)
        result = attest([fetch(root) for root in receipt_roots(args.db, fetch)], cli=args.cli)
    except Exception as error:
        print(json.dumps({"published": False, "error_type": type(error).__name__}))
        raise SystemExit(2) from None
    print(json.dumps({"published": True, "providers": result}, indent=2))
