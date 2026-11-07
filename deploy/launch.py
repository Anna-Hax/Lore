"""Load only this service's mounted secret file, then exec that service.

Variable names are the ones P1's services read (agents/runtime.py, gateway/__main__.py).
"""

import os
from pathlib import Path
import re

# LORE_SERVICE_TOKEN is the one secret all three share: the verifier and curator send it to the gateway's
# /internal/* API, which has no other login (P1, hosted MCP change).
REQUIRED = {
    # TURNKEY_*_PRIVATE_KEY: Lore's Turnkey parent-org key and its delegated key in users' wallets (gateway/turnkey.py).
    "gateway": {"MASTER_KEY", "WM_SECRET", "LORE_GATEWAY_KEY", "ZG_STORAGE_PRIVATE_KEY", "LORE_SERVICE_TOKEN",
                "TURNKEY_API_PRIVATE_KEY", "TURNKEY_DELEGATED_PRIVATE_KEY", "WORLD_RP_SIGNING_KEY"},
    "verifier": {"LORE_VERIFIER_KEY", "ZG_API_KEY", "ZG_STORAGE_PRIVATE_KEY", "LORE_SERVICE_TOKEN"},
    "curator": {"LORE_CURATOR_KEY", "ZG_API_KEY", "ZG_STORAGE_PRIVATE_KEY", "LORE_SERVICE_TOKEN"},
}
# Allowed but not required, and not hex keys. WORLD_IDP_CLIENT_SECRET: World ID Agent Pass (gateway/worldidp.py),
# on only when compose also sets WORLD_IDP_CLIENT_ID.
OPTIONAL = {"gateway": {"WORLD_IDP_CLIENT_SECRET"}, "verifier": set(), "curator": set()}
FREE_FORM = {"ZG_API_KEY", "WORLD_IDP_CLIENT_SECRET"}


def secret_environment(service: str, text: str) -> dict[str, str]:
    if service not in REQUIRED:
        raise ValueError("unknown Lore service")
    values = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if not separator or name not in REQUIRED[service] | OPTIONAL[service] or name in values or not value:
            raise ValueError("invalid or unexpected service secret entry")
        if name not in FREE_FORM and not re.fullmatch(r"(?:0x)?[0-9a-fA-F]{64}", value):
            raise ValueError("invalid key encoding")
        values[name] = value
    if not REQUIRED[service] <= set(values):
        raise ValueError("required service secrets are missing")
    return values


def main():
    try:
        service = os.environ["LORE_SERVICE"]
        values = secret_environment(service, Path("/run/secrets/lore.env").read_text())
    except (OSError, KeyError, ValueError):
        raise SystemExit("Lore startup configuration is incomplete or invalid") from None
    os.environ.update(values)
    os.execvp("python", ["python", "-m", service])


if __name__ == "__main__":
    main()
