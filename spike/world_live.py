#!/usr/bin/env python3
"""Spike W1, W3 and W4 against World itself: real proofs from World App or the simulator, verified by World's API.

Needs WORLD_APP_ID, WORLD_RP_ID, WORLD_RP_SIGNING_KEY (and optionally WORLD_ACTION) in the environment, plus
`npm ci --ignore-scripts` in spike/world. Run from agents/ so the deps resolve:
    uv run python ../spike/world_live.py --preset orbLegacy --rounds 2 --wait 660
Use --wait 660 for proofOfHuman: World's wallet only starts refusing a reused 4.0 nullifier after 10 minutes.
Writes spike/local-evidence/world-live.json (gitignored). Nullifiers are stored only as fingerprints.
"""

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import httpx
from eth_utils import keccak

from world_rp import hash_signal, rp_context

HERE = Path(__file__).parent
VERIFY_URL = "https://developer.world.org/api/v4/verify/{rp_id}"


def prove(cfg: dict, show=print) -> dict:
    """One IDKit request through the real SDK. Returns its completion: {success, result} or {success, error}."""
    p = subprocess.Popen(["node", "driver.mjs", "request"], cwd=HERE / "world", text=True,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    p.stdin.write(json.dumps(cfg))
    p.stdin.close()
    completion = None
    for line in p.stdout:
        msg = json.loads(line)
        if "connector" in msg:
            show(f"Open with World App or the simulator:\n{msg['connector']}")
        completion = msg.get("completion", completion)
    if p.wait() != 0 or completion is None:
        raise RuntimeError("IDKit driver failed")
    return completion


def fingerprint(nullifier) -> str | None:
    return None if nullifier is None else keccak(text=str(nullifier).lower()).hex()[:16]


def verify(http: httpx.Client, rp_id: str, result: dict) -> dict:
    r = http.post(VERIFY_URL.format(rp_id=rp_id), json=result)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    return {"status": r.status_code, "success": body.get("success"), "code": body.get("code"),
            "detail": body.get("detail"),
            "results": [{"identifier": x.get("identifier"), "success": x.get("success"), "code": x.get("code"),
                         "nullifier": fingerprint(x.get("nullifier"))} for x in body.get("results", [])]}


def run_round(http, app_id, rp_id, key, action, preset, environment, fake_reply=None, show=print) -> tuple[dict, dict | None]:
    signal = secrets.token_hex(16)
    cfg = {"app_id": app_id, "action": action, "rp_context": rp_context(rp_id, key, action), "signal": signal,
           "preset": preset, "allow_legacy_proofs": True, "environment": environment}
    if fake_reply:
        cfg["fake_reply"] = fake_reply
    completion = prove(cfg, show)
    if not completion.get("success"):
        return {"preset": preset, "idkit_error": completion.get("error")}, None
    result = completion["result"]
    return {"preset": preset, "protocol_version": result.get("protocol_version"),
            "identifiers": [x.get("identifier") for x in result["responses"]],
            "signal_hash_matches": all(x.get("signal_hash") == hash_signal(signal) for x in result["responses"]),
            "verify": verify(http, rp_id, result)}, result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--preset", default="orbLegacy", choices=["orbLegacy", "deviceLegacy", "proofOfHuman"])
    ap.add_argument("--env", default="production", choices=["production", "staging"])
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--wait", type=int, default=0, help="seconds between rounds")
    args = ap.parse_args()
    missing = [n for n in ("WORLD_APP_ID", "WORLD_RP_ID", "WORLD_RP_SIGNING_KEY") if not os.environ.get(n)]
    if missing:
        print("not run, missing: " + ", ".join(missing))
        return 2
    action = os.environ.get("WORLD_ACTION", "lore-person")
    http = httpx.Client(timeout=30)
    rounds, first = [], None
    for i in range(args.rounds):
        if i and args.wait:
            print(f"waiting {args.wait}s")
            time.sleep(args.wait)
        record, result = run_round(http, os.environ["WORLD_APP_ID"], os.environ["WORLD_RP_ID"],
                                   os.environ["WORLD_RP_SIGNING_KEY"], action, args.preset, args.env)
        rounds.append(record)
        print(json.dumps(record))
        first = first or result
    nullifiers = {x["nullifier"] for r in rounds for x in r.get("verify", {}).get("results", []) if x["nullifier"]}
    out = {"at": int(time.time()), "environment": args.env, "action": action, "rounds": rounds,
           "distinct_nullifiers": len(nullifiers),
           "same_proof_sent_again": verify(http, os.environ["WORLD_RP_ID"], first) if first else None}
    path = HERE / "local-evidence" / "world-live.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, indent=2))
    print(f"wrote {path}")
    return 0 if all(r.get("verify", {}).get("success") for r in rounds) else 1


if __name__ == "__main__":
    sys.exit(main())
