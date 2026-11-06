"""Network config. Values for 16602 and 16661 come from the official 0G docs
(https://docs.0g.ai/ai-context.md, checked 2026-11-06). Don't edit them without re-checking the docs.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Network:
    name: str
    chain_id: int
    rpc_url: str
    explorer: str | None
    faucet: str | None
    storage_indexer: str  # 0G Storage indexer (turbo)
    storage_flow: str | None  # 0G Storage flow contract


NETWORKS: dict[int, Network] = {
    # 0G Galileo testnet: the v1 target. The docs mark this public RPC as development-only.
    16602: Network(
        name="0G Galileo Testnet",
        chain_id=16602,
        rpc_url="https://evmrpc-testnet.0g.ai",
        explorer="https://chainscan-galileo.0g.ai",
        faucet="https://faucet.0g.ai",
        storage_indexer="https://indexer-storage-testnet-turbo.0g.ai",
        storage_flow="0x22E03a6A89B950F1c82ec5e74F8eCa321a105296",
    ),
    # 0G Aristotle mainnet: reference only, not used in v1.
    16661: Network(
        name="0G Mainnet",
        chain_id=16661,
        rpc_url="https://evmrpc.0g.ai",
        explorer="https://chainscan.0g.ai",
        faucet=None,
        storage_indexer="https://indexer-storage-turbo.0g.ai",
        storage_flow="0x62D4144dB0F0a6fBBaeb6296c785C71B3D57C526",
    ),
    # Local anvil for development. Contracts run locally, but storage still goes to the
    # 0G testnet indexer, because there is no local 0G Storage. Uploads need a testnet-funded key.
    31337: Network(
        name="Anvil (local)",
        chain_id=31337,
        rpc_url="http://127.0.0.1:8545",
        explorer=None,
        faucet=None,
        storage_indexer="https://indexer-storage-testnet-turbo.0g.ai",
        storage_flow="0x22E03a6A89B950F1c82ec5e74F8eCa321a105296",
    ),
}

# The chain v1 targets.
DEFAULT_CHAIN_ID = 16602


def get_network(chain_id: int = DEFAULT_CHAIN_ID) -> Network:
    try:
        return NETWORKS[chain_id]
    except KeyError:
        raise ValueError(f"Unknown chain_id {chain_id}") from None
