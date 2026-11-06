"""Create local role wallets without displaying keys or overwriting old keys.

Each service gets its own storage wallet, because concurrent uploads from one
wallet would race on nonces. ZG_API_KEY starts blank: launch.py refuses to start
until the operator adds a key created with trust_mode "private".
"""

import argparse
import json
import os
from pathlib import Path
import secrets

from eth_account import Account

WALLETS = ("gateway", "verifier", "curator", "gateway_storage", "verifier_storage", "curator_storage", "attestation")


def create(directory: Path) -> dict:
    directory.mkdir(mode=0o700)  # Existing directories are deliberately refused.
    accounts = {name: Account.create() for name in WALLETS}
    key = lambda name: accounts[name].key.hex()  # noqa: E731
    service_token = secrets.token_hex(32)  # shared by gateway, verifier and curator for /internal/*
    files = {
        "gateway.env": {
            "MASTER_KEY": secrets.token_hex(32), "WM_SECRET": secrets.token_hex(32),
            "LORE_GATEWAY_KEY": key("gateway"), "ZG_STORAGE_PRIVATE_KEY": key("gateway_storage"),
            "LORE_SERVICE_TOKEN": service_token,
        },
        "verifier.env": {"LORE_VERIFIER_KEY": key("verifier"), "ZG_API_KEY": "", "ZG_STORAGE_PRIVATE_KEY": key("verifier_storage"),
                         "LORE_SERVICE_TOKEN": service_token},
        "curator.env": {"LORE_CURATOR_KEY": key("curator"), "ZG_API_KEY": "", "ZG_STORAGE_PRIVATE_KEY": key("curator_storage"),
                        "LORE_SERVICE_TOKEN": service_token},
        "attestation.env": {"ZG_STORAGE_PRIVATE_KEY": key("attestation")},
    }
    for name, values in files.items():
        descriptor = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write("".join(f"{name}={value}\n" for name, value in values.items()))
    addresses = {name: account.address for name, account in accounts.items()}
    (directory / "addresses.json").write_text(json.dumps(addresses, indent=2) + "\n")
    return addresses


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "secrets")
    args = parser.parse_args()
    try:
        addresses = create(args.output)
    except FileExistsError:
        raise SystemExit("Refusing to replace existing secrets; see RUNBOOK.md") from None
    print(json.dumps({"created": True, "addresses": addresses}, indent=2))
