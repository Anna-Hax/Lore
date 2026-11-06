"""Resolve keys at call time; importing the package never loads secrets."""

import os
import re


def secret_bytes(value: bytes | None, name: str) -> bytes:
    if value is None:
        encoded = os.environ.get(name, "")
        if not re.fullmatch(r"(?:0x)?[0-9a-fA-F]{64}", encoded):
            raise ValueError(f"{name} must contain a 32-byte hex key")
        value = bytes.fromhex(encoded.removeprefix("0x"))
    if not isinstance(value, bytes) or len(value) != 32:
        raise ValueError(f"{name} must be exactly 32 bytes")
    return value
