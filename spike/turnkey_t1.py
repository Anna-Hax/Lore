"""Spike T1: Lore's Turnkey delegated access against the live Turnkey API and 0G Galileo (BUILD_PLAN, spike T1).

Creates ONE test wallet exactly the way lore_create_wallet does (gateway/turnkey.py), then checks:
  - the activity versions and result fields work (the wallet gets created at all);
  - a retry with the same start time replays the same activities (same sub-org, no second wallet);
  - Lore's delegated user is found by whoami, and only the test user is left in the root quorum;
  - Turnkey's policy engine signs Lore's calls (USDC approve to Access, Submissions.vote) and the signature
    recovers to the wallet, and denies: approve to any other spender, another contract, another chain id,
    native value, and gas above MAX_GAS;
  - with --broadcast: the signed approve is accepted on chain 16602 (fund the printed address with testnet 0G).

Secrets come from .env.turnkey at the repo root (gitignored, never printed):
  TURNKEY_ORGANIZATION_ID, TURNKEY_API_PUBLIC_KEY, TURNKEY_API_PRIVATE_KEY   Lore's parent-org API key (dashboard)
  T1_EMAIL                                                                  the test user's email (one you control)
  TURNKEY_DELEGATED_PUBLIC_KEY, TURNKEY_DELEGATED_PRIVATE_KEY               generated and saved there if missing

    cd agents && uv run python ../spike/turnkey_t1.py [--broadcast]

Re-running reuses the same test wallet (spike/local-evidence/turnkey-t1.json). Results go to
spike/local-evidence/turnkey-t1-result.json (gitignored: it holds Turnkey ids, not secrets).
"""

import argparse
import json
import os
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from eth_account import Account  # noqa: E402

from chain import Chain  # noqa: E402
from gateway.service import POLICY_CALLS  # noqa: E402
from gateway.signer import Signer  # noqa: E402
from gateway.turnkey import MAX_GAS, RETRY_WINDOW_MS, Turnkey, TurnkeyError, lore_policies, unsigned_eip1559  # noqa: E402

ENV, STATE = ROOT / ".env.turnkey", ROOT / "spike" / "local-evidence" / "turnkey-t1.json"
RESULT = STATE.with_name("turnkey-t1-result.json")
CHAIN_ID = 16602
OTHER = "0x" + "77" * 20  # a spender / recipient that isn't Lore's


def load_env() -> dict:
    if not ENV.exists():
        raise SystemExit(f"create {ENV} (see this file's docstring) first")
    env = {}
    for line in ENV.read_text().splitlines():
        name, sep, value = line.partition("=")
        if sep and value.strip() and not line.lstrip().startswith("#"):
            env[name.strip()] = value.strip()
    missing = {"TURNKEY_ORGANIZATION_ID", "TURNKEY_API_PUBLIC_KEY", "TURNKEY_API_PRIVATE_KEY", "T1_EMAIL"} - set(env)
    if missing:
        raise SystemExit(f"{ENV.name} is missing: {', '.join(sorted(missing))}")
    if "TURNKEY_DELEGATED_PRIVATE_KEY" not in env:  # same key shape create_secrets.py makes
        key = ec.generate_private_key(ec.SECP256R1())
        env["TURNKEY_DELEGATED_PUBLIC_KEY"] = key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.CompressedPoint).hex()
        env["TURNKEY_DELEGATED_PRIVATE_KEY"] = format(key.private_numbers().private_value, "064x")
        with ENV.open("a") as f:
            f.write(f"\nTURNKEY_DELEGATED_PUBLIC_KEY={env['TURNKEY_DELEGATED_PUBLIC_KEY']}\n"
                    f"TURNKEY_DELEGATED_PRIVATE_KEY={env['TURNKEY_DELEGATED_PRIVATE_KEY']}\n")
        print("generated a delegated key pair and saved it in .env.turnkey")
    os.chmod(ENV, 0o600)
    return env


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--broadcast", action="store_true", help="also send the allowed approve on 16602")
    args = parser.parse_args()
    env = load_env()
    tk = Turnkey(env["TURNKEY_ORGANIZATION_ID"], (env["TURNKEY_API_PUBLIC_KEY"], env["TURNKEY_API_PRIVATE_KEY"]),
                 (env["TURNKEY_DELEGATED_PUBLIC_KEY"], env["TURNKEY_DELEGATED_PRIVATE_KEY"]))
    chain = Chain.for_chain(CHAIN_ID)
    contracts = {n: chain.address(n) for n in POLICY_CALLS}
    selectors = {f"{c}.{fn}": chain.selector(c, fn) for c, fns in POLICY_CALLS.items() for fn in fns}
    policies = lambda uid: lore_policies(uid, CHAIN_ID, contracts, selectors)  # noqa: E731
    results, ok = {}, True

    def check(name: str, passed: bool, detail) -> None:
        nonlocal ok
        ok &= passed
        results[name] = {"pass": passed, "detail": detail}
        print(f"{'PASS' if passed else 'FAIL'}  {name}: {detail}")

    # 1. Create the wallet (or resume / reuse the stored one), then replay to prove retries are safe.
    STATE.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if not state:
        state = {"person": "0x" + secrets.token_hex(32), "ms": int(time.time() * 1000)}
        STATE.write_text(json.dumps(state))
    fresh = int(time.time() * 1000) - state["ms"] < RETRY_WINDOW_MS
    if "sub" not in state or fresh:
        if not fresh:
            raise SystemExit(f"the stored attempt is over an hour old and unfinished; delete {STATE} to start over")
        try:
            sub, address = tk.create_wallet(state["person"], env["T1_EMAIL"], policies, state["ms"])
        except TurnkeyError as e:
            check("create_wallet", False, str(e))
            return finish(results, ok)
        first = "sub" not in state
        state.update(sub=sub, address=address)
        STATE.write_text(json.dumps(state))
        check("create_wallet", True, {"sub_org": sub, "address": address, "first_run": first})
        again = tk.create_wallet(state["person"], env["T1_EMAIL"], policies, state["ms"])
        check("retry replays the same activities", again == (sub, address), {"retry": again})
    sub, address = state["sub"], state["address"]

    # 2. Who is left in charge of the sub-org. Query shapes are best effort: a failure here is reported, not fatal.
    me = tk._post(tk.delegated, "/public/v1/query/whoami", {"organizationId": sub})
    check("whoami (Lore's delegated user)", bool(me.get("userId")), {"userId": me.get("userId")})
    for path, pick in (("/public/v1/query/list_policies", lambda r: sorted(p["policyName"] for p in r["policies"])),
                       ("/public/v1/query/get_organization_configs", lambda r: r["configs"]["quorum"])):
        try:
            value = pick(tk._post(tk.delegated, path, {"organizationId": sub}))
            if path.endswith("list_policies"):
                check("policies in place", len([p for p in value if p.startswith("Lore: ")]) == len(policies("x")), value)
            else:
                check("root quorum is the user only", me.get("userId") not in value.get("userIds", []), value)
        except Exception as e:  # noqa: BLE001
            check(path, False, f"query failed: {e}")

    # 3. Policy engine: what Lore's key may and may not sign.
    price = chain.topic_price()
    usdc, access = chain.c["USDC"], contracts["Access"]
    base = {"chainId": CHAIN_ID, "nonce": 0, "gas": 100_000, "maxPriorityFeePerGas": 10**9, "maxFeePerGas": 10**10,
            "value": 0, "accessList": []}
    approve = {**base, "to": contracts["USDC"], "data": usdc.encode_abi("approve", args=[access, price])}
    vote = {**base, "to": contracts["Submissions"], "data": chain.c["Submissions"].encode_abi("vote", args=[1, True])}
    cases = {
        "allow: USDC.approve(Access)": (approve, True),
        "allow: Submissions.vote": (vote, True),
        "deny: USDC.approve(other spender)": ({**approve, "data": usdc.encode_abi("approve", args=[OTHER, price])}, False),
        "deny: USDC.transfer": ({**approve, "data": usdc.encode_abi("transfer", args=[OTHER, 1])}, False),
        "deny: approve calldata sent to another contract": ({**approve, "to": OTHER}, False),
        "deny: another chain id": ({**approve, "chainId": 1}, False),
        "deny: native value": ({**vote, "value": 1}, False),
        "deny: gas above MAX_GAS": ({**vote, "gas": MAX_GAS + 1}, False),
    }
    for name, (tx, allowed) in cases.items():
        try:
            raw = tk.sign_transaction(sub, address, unsigned_eip1559(tx))
            signer = Account.recover_transaction(raw)
            check(name, allowed and signer.lower() == address.lower(), {"signed": True, "recovered": signer})
        except TurnkeyError as e:
            check(name, not allowed, {"signed": False, "turnkey": str(e)[:300]})

    # 4. The real path the gateway uses: Signer builds, Turnkey signs, the RPC accepts.
    if args.broadcast:
        balance = chain.w3.eth.get_balance(chain.w3.to_checksum_address(address))
        if not balance:
            check("broadcast", False, f"fund {address} with a little Galileo 0G (https://faucet.0g.ai), then rerun")
        else:
            signer = Signer(chain, tk, lambda a: sub if a.lower() == address.lower() else None)
            prepared = chain.prepare("USDC", "approve", chain.w3.to_checksum_address(address), access, price)
            try:
                check("broadcast: approve mined on 16602", True, {"tx": signer.send(prepared)})
            except Exception as e:  # noqa: BLE001
                check("broadcast: approve mined on 16602", False, str(e))
    else:
        print(f"(skipped broadcast: fund {address} with Galileo 0G and rerun with --broadcast)")
    finish(results, ok)


def finish(results: dict, ok: bool) -> None:
    RESULT.write_text(json.dumps(results, indent=2))
    print(f"\n{'T1 PASSED' if ok else 'T1 FAILED'} · details in {RESULT.relative_to(ROOT)}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
