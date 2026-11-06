"""Create local role wallets without displaying keys or overwriting old keys.

Each service gets its own storage wallet, because concurrent uploads from one
wallet would race on nonces. ZG_API_KEY starts blank: launch.py refuses to start
until the operator adds a key created with trust_mode "private". Likewise
TURNKEY_API_PRIVATE_KEY, which Turnkey issues for Lore's parent organization.
WORLD_RP_SIGNING_KEY also starts blank: use the key registered for Lore's World RP.
Lore's delegated Turnkey key is generated here: its public half goes in
addresses.json (set it as TURNKEY_DELEGATED_PUBLIC_KEY); it is not secret.
"""

import argparse
import json
import os
from pathlib import Path
import secrets

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from eth_account import Account

WALLETS = ("gateway", "verifier", "curator", "gateway_storage", "verifier_storage", "curator_storage", "attestation")


def create(directory: Path) -> dict:
    directory.mkdir(mode=0o700)  # Existing directories are deliberately refused.
    accounts = {name: Account.create() for name in WALLETS}
    key = lambda name: accounts[name].key.hex()  # noqa: E731
    service_token = secrets.token_hex(32)  # shared by gateway, verifier and curator for /internal/*
    delegated = ec.generate_private_key(ec.SECP256R1())  # Lore's delegated user in every user's Turnkey sub-org
    delegated_public = delegated.public_key().public_bytes(serialization.Encoding.X962,
                                                           serialization.PublicFormat.CompressedPoint).hex()
    files = {
        "gateway.env": {
            "MASTER_KEY": secrets.token_hex(32), "WM_SECRET": secrets.token_hex(32),
            "LORE_GATEWAY_KEY": key("gateway"), "ZG_STORAGE_PRIVATE_KEY": key("gateway_storage"),
            "LORE_SERVICE_TOKEN": service_token, "TURNKEY_API_PRIVATE_KEY": "",
            "WORLD_RP_SIGNING_KEY": "",
            "TURNKEY_DELEGATED_PRIVATE_KEY": format(delegated.private_numbers().private_value, "064x"),
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
    addresses["turnkey_delegated_public_key"] = delegated_public
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
