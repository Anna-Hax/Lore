"""Offline readiness evidence for S; no secrets, model calls or transactions.

Run from the repo root: python3.12 spike/preflight.py
Exit 0 = prerequisites present (NOT a live pass); 2 = live prerequisites missing.
"""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys

REPO = Path(__file__).resolve().parents[1]


def collect() -> dict:
    required_env = ("ZG_API_KEY", "ZG_MODEL", "ZG_STORAGE_PRIVATE_KEY")
    return {
        "kind": "offline-preflight",
        "live_checks_executed": False,
        "python": ".".join(map(str, sys.version_info[:3])),
        "python_supported": sys.version_info >= (3, 12),
        "environment_present": {name: bool(os.environ.get(name)) for name in required_env},
        "tools_present": {name: shutil.which(name) is not None for name in ("lore-storage-client", "0g-compute-cli", "docker")},
        "modules_present": {name: importlib.util.find_spec(name) is not None for name in ("openai", "web3", "eth_account")},
        "team_files_present": {
            "network_config": (REPO / "shared/lore_shared/network.py").is_file(),
            "zg_client": (REPO / "agents/zg").is_dir(),
            "hosted_mcp": (REPO / "agents/gateway/mcp_server.py").is_file(),
        },
    }


def ready(report: dict) -> bool:
    return report["python_supported"] and all(
        all(report[group].values())
        for group in ("environment_present", "tools_present", "modules_present", "team_files_present")
    )


if __name__ == "__main__":
    report = collect()
    print(json.dumps(report, sort_keys=True, indent=2))
    raise SystemExit(0 if ready(report) else 2)
