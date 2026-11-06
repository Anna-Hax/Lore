"""P2's contract artifacts (ABIs, deployments, network config).

Bundled into the wheel from shared/lore_shared (see pyproject force-include), so `uvx lore-mcp`
works with no extra files. In a repo checkout it reads shared/lore_shared directly.
"""

import importlib.util
import json
from pathlib import Path

_BUNDLED = Path(__file__).parent / "contracts_data"
DIR = _BUNDLED if _BUNDLED.exists() else Path(__file__).resolve().parents[2] / "shared" / "lore_shared"
ABI_FILE = {"USDC": "MockUSDC"}
DEFAULT_CHAIN_ID = 16602  # P2's 0G Galileo testnet deployment


def abi(name: str) -> list:
    return json.loads((DIR / "abi" / f"{ABI_FILE.get(name, name)}.json").read_text())


def deployment(chain_id: int) -> dict:
    return json.loads((DIR / "deployments" / f"{chain_id}.json").read_text())


def rpc_url(chain_id: int) -> str:
    spec = importlib.util.spec_from_file_location("lore_network", DIR / "network.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.get_network(chain_id).rpc_url
