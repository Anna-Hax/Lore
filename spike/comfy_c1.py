"""Spike C1: can Lore's purchase contract buy comfy author tokens atomically, and can the gateway read their price?

Read-only and free. It reads 0G mainnet (16661) and simulates the buy with eth_call, giving a made-up address a
fake balance for the duration of the call. Nothing is signed or sent.

  1. Finds the latest comfy launch (AgentLauncher `Launched` events).
  2. Reads its pool key (`poolIdToPoolKey`) and spot price (`getSlot0`). The gateway's price keeper reads these.
  3. Simulates `ComfyRouter.buyExactWithNative(key, amount, recipient, deadline)`: buy an exact number of tokens
     for 0G, unused 0G refunded to the caller. `Access.buy` will make this call once per author.

    cd agents && uv run python ../spike/comfy_c1.py

Addresses come from comfy's docs (https://www.comfy.fun/docs/build/integrate) and its own trades: 3,359
`ChargeTaken` events name this router. Its verified source is on chainscan.
"""

import time

from eth_abi import decode
from web3 import Web3

RPC = "https://evmrpc.0g.ai"  # shared/lore_shared/network.py, 16661
LAUNCHER = "0x2F74d603f7B7D8B7BFc78ef04E09905B862bE86a"
POOL_MANAGER = "0xAabD31f24914B48dAEA998e69683225E289d08b0"
ROUTER = "0x76526f4815447f693468ef44e0204a0689178d9e"
LAUNCHED = "0x20c8f644fcaa2f5b4960a99c98327b3d5bd9838194dae4a67dd914ec9c8249fe"
TOKENS = 1000  # whole tokens to simulate buying

KEY = {"name": "key", "type": "tuple", "components": [{"name": n, "type": t} for n, t in (
    ("currency0", "address"), ("currency1", "address"), ("hooks", "address"), ("poolManager", "address"),
    ("fee", "uint24"), ("parameters", "bytes32"))]}
POOL_ABI = [
    {"name": "poolIdToPoolKey", "type": "function", "stateMutability": "view", "inputs": [{"name": "id", "type": "bytes32"}],
     "outputs": KEY["components"]},
    {"name": "getSlot0", "type": "function", "stateMutability": "view", "inputs": [{"name": "id", "type": "bytes32"}],
     "outputs": [{"name": "sqrtPriceX96", "type": "uint160"}, {"name": "tick", "type": "int24"},
                 {"name": "protocolFee", "type": "uint24"}, {"name": "lpFee", "type": "uint24"}]},
]
ROUTER_ABI = [{"name": "buyExactWithNative", "type": "function", "stateMutability": "payable",
               "inputs": [KEY, {"name": "amountOut", "type": "uint256"}, {"name": "recipient", "type": "address"},
                          {"name": "deadline", "type": "uint256"}],
               "outputs": [{"name": "amountIn", "type": "uint256"}]}]


def spot_0g_per_token(sqrt_price_x96: int) -> float:
    """currency0 is native 0G, so the pool price is tokens per 0G; invert it."""
    return 1 / (sqrt_price_x96 / 2**96) ** 2


def main() -> None:
    w3 = Web3(Web3.HTTPProvider(RPC))
    assert w3.eth.chain_id == 16661, "not 0G mainnet"
    head = w3.eth.block_number
    logs = []
    for start in range(head - 500_000, head, 100_000):  # comfy's docs: query 100,000 blocks at a time
        logs += w3.eth.get_logs({"address": Web3.to_checksum_address(LAUNCHER), "topics": [LAUNCHED],
                                 "fromBlock": start, "toBlock": min(start + 99_999, head)})
    assert logs, "no comfy launches in the last 500k blocks"
    pool_id = bytes(logs[-1]["topics"][1])

    pm = w3.eth.contract(address=Web3.to_checksum_address(POOL_MANAGER), abi=POOL_ABI)
    key = pm.functions.poolIdToPoolKey(pool_id).call()
    assert key[0] == "0x" + "00" * 20, "expected native 0G as currency0"
    price = spot_0g_per_token(pm.functions.getSlot0(pool_id).call()[0])
    print(f"token {key[1]}: spot {price:.10f} 0G per token (pool 0x{pool_id.hex()})")

    router = w3.eth.contract(address=Web3.to_checksum_address(ROUTER), abi=ROUTER_ABI)
    fake = Web3.to_checksum_address("0x00000000000000000000000000000000000c0ffe")
    call = {"from": fake, "to": router.address, "value": w3.to_wei(10, "ether"),
            "data": router.encode_abi("buyExactWithNative", args=[key, TOKENS * 10**18, fake, int(time.time()) + 600])}
    state = {fake: {"balance": hex(10**22)}}  # simulation only
    cost = decode(["uint256"], w3.eth.call(call, "latest", state))[0] / 1e18
    gas = w3.eth.estimate_gas(call, "latest", state)
    print(f"simulated buy of {TOKENS} tokens: {cost:.6f} 0G (spot {TOKENS * price:.6f}), {gas} gas")
    assert cost >= TOKENS * price * 0.99, "cost below spot: price derivation is wrong"


if __name__ == "__main__":
    main()
