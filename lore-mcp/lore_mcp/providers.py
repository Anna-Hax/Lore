"""Find a 0G Compute provider's TEE signer, read directly from the chain (spike S2), never from Lore.

Mirrors agents/zg/providers.py: lore-mcp ships standalone, so it can't import Lore's agents.

Reads getService on 0G's Compute Inference contract. The Router's providers are on 0G mainnet (16661),
not Galileo, so this is a separate read-only connection whatever chain Lore's contracts are on.
"""

import json

from web3 import Web3

from lore_mcp import contracts

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
ABI = [{
    "type": "function", "name": "getService", "stateMutability": "view",
    "inputs": [{"name": "provider", "type": "address"}],
    "outputs": [{"name": "service", "type": "tuple", "components": [{"name": n, "type": t} for n, t in _FIELDS]}],
}]


def expected_signer(service: dict) -> str:
    """BUILD_PLAN 2.1 step 3.4: targetTeeAddress when targetSeparated, else teeSignerAddress."""
    try:
        info = json.loads(service["additionalInfo"] or "{}")
    except ValueError:
        info = {}
    if isinstance(info, dict) and info.get("targetSeparated") is True:
        return Web3.to_checksum_address(info["targetTeeAddress"])
    return service["teeSignerAddress"]


class Providers:
    def __init__(self, chain_id: int = 16661, rpc: str | None = None):
        w3 = Web3(Web3.HTTPProvider(rpc or contracts.rpc_url(chain_id), request_kwargs={"timeout": 20}))
        self.serving = w3.eth.contract(address=INFERENCE[chain_id], abi=ABI)
        self._cache = {}

    def service(self, provider: str) -> dict:
        row = self.serving.functions.getService(Web3.to_checksum_address(provider)).call()
        return dict(zip((n for n, _ in _FIELDS), row, strict=True))

    def __call__(self, provider: str) -> tuple[str, str]:
        """zg.ProviderInfo: (url, expected TEE signer). Only TeeML providers: the model runs inside the TEE."""
        if provider not in self._cache:  # a provider's record changes rarely; cache per process
            s = self.service(provider)
            if s["verifiability"] != "TeeML":
                raise ValueError(f"provider {provider} is {s['verifiability']!r}, not TeeML")
            self._cache[provider] = (s["url"].rstrip("/"), expected_signer(s))
        return self._cache[provider]
