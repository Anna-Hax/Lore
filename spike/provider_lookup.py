"""S2, read-only: find a provider's URL and TEE signer in 0G's Compute Inference contract.

No wallet, API key or transaction. Addresses come from https://docs.0g.ai/ai-context.md
and the official SDK's src.ts/sdk/constants.ts; the struct from its InferenceServing ABI.

Run: uv run --project shared --group platform python spike/provider_lookup.py --chain-id 16661
"""

import argparse
import json

from web3 import Web3

from lore_shared.network import get_network

INFERENCE = {
    16602: "0xa79F4c8311FF93C06b8CfB403690cc987c93F91E",
    16661: "0x47340d900bdFec2BD393c626E12ea0656F938d84",
}
_FIELDS = [
    ("provider", "address"), ("serviceType", "string"), ("url", "string"),
    ("inputPrice", "uint256"), ("outputPrice", "uint256"), ("updatedAt", "uint256"),
    ("model", "string"), ("verifiability", "string"), ("additionalInfo", "string"),
    ("teeSignerAddress", "address"), ("teeSignerAcknowledged", "bool"),
]
_SERVICE = {"type": "tuple", "components": [{"name": n, "type": t} for n, t in _FIELDS]}
ABI = [
    {"type": "function", "name": "getService", "stateMutability": "view",
     "inputs": [{"name": "provider", "type": "address"}],
     "outputs": [{**_SERVICE, "name": "service"}]},
    {"type": "function", "name": "getAllServices", "stateMutability": "view",
     "inputs": [{"name": "offset", "type": "uint256"}, {"name": "limit", "type": "uint256"}],
     "outputs": [{**_SERVICE, "type": "tuple[]", "name": "services"}, {"name": "total", "type": "uint256"}]},
]


def expected_signer(service: dict) -> str:
    """BUILD_PLAN 2.1 step 3.4: targetTeeAddress when targetSeparated, else teeSignerAddress."""
    try:
        info = json.loads(service["additionalInfo"] or "{}")
    except ValueError:
        info = {}
    if isinstance(info, dict) and info.get("targetSeparated") is True:
        return Web3.to_checksum_address(info["targetTeeAddress"])
    return service["teeSignerAddress"]


def contract(chain_id: int):
    web3 = Web3(Web3.HTTPProvider(get_network(chain_id).rpc_url, request_kwargs={"timeout": 20}))
    return web3.eth.contract(address=INFERENCE[chain_id], abi=ABI)


def services(chain_id: int, page: int = 50) -> list[dict]:
    serving, found, offset = contract(chain_id), [], 0
    while True:
        rows, total = serving.functions.getAllServices(offset, page).call()
        found += [dict(zip((name for name, _ in _FIELDS), row, strict=True)) for row in rows]
        offset += len(rows)
        if not rows or offset >= total:
            return found


def summary(service: dict) -> dict:
    try:
        info = json.loads(service["additionalInfo"] or "{}")
    except ValueError:
        info = {}
    return {
        "provider": service["provider"], "model": service["model"], "type": service["serviceType"],
        "url": service["url"], "verifiability": service["verifiability"],
        "tee_signer": service["teeSignerAddress"], "signer_acknowledged": service["teeSignerAcknowledged"],
        "target_separated": info.get("targetSeparated") if isinstance(info, dict) else None,
        "expected_signer": expected_signer(service),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain-id", type=int, choices=sorted(INFERENCE), default=16661)
    args = parser.parse_args()
    rows = [summary(service) for service in services(args.chain_id)]
    print(json.dumps({"chain_id": args.chain_id, "contract": INFERENCE[args.chain_id],
                      "service_count": len(rows), "services": rows}, indent=2))
