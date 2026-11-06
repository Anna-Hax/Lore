"""Bundle P2's contract artifacts from ../shared/lore_shared into lore_mcp/contracts_data.

Only when ../shared exists (building inside the repo). A wheel built from the sdist finds the
files already in place, because the sdist was built here with them included.
"""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        src = Path(self.root).parent / "shared" / "lore_shared"
        if src.exists():
            for item in ("abi", "deployments", "network.py"):
                build_data["force_include"][str(src / item)] = f"lore_mcp/contracts_data/{item}"
