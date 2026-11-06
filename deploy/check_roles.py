"""Read-only launch check: do the generated wallets hold their on-chain roles and gas?"""

import argparse
import json
from pathlib import Path

from lore_shared.chain import ChainReader

ROLES = {"gateway": "LEAK_DETECTOR_ROLE", "verifier": "VERIFIER_ROLE", "curator": "CURATOR_ROLE"}


def check(reader, addresses: dict) -> dict:
    roles = {
        name: reader.call("LoreRoles", "hasRole", reader.call("LoreRoles", role), addresses[name])
        for name, role in ROLES.items()
    }
    funded = {name: reader.web3.eth.get_balance(address) > 0 for name, address in addresses.items()}
    return {"roles": roles, "funded": funded, "ready": all(roles.values()) and all(funded.values())}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--addresses", type=Path, default=Path(__file__).parent / "secrets/addresses.json")
    parser.add_argument("--chain-id", type=int, default=16602)
    args = parser.parse_args()
    report = check(ChainReader(args.chain_id), json.loads(args.addresses.read_text()))
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["ready"] else 2)
