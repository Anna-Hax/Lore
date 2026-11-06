"""Read-only P2 deployment check. No wallet or secrets are needed."""

import argparse
import json

from lore_shared.chain import ChainReader


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain-id", type=int, default=16602)
    args = parser.parse_args()
    try:
        report = ChainReader(args.chain_id).validate()
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__, "live_check_passed": False}))
        raise SystemExit(2) from None
    print(json.dumps({"status": "passed", "live_check_passed": True, **report}, indent=2))
