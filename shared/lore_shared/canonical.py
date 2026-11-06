"""One JSON encoding for metadata, reports and receipts hashed on-chain."""

import json
import math
from typing import Any

from eth_hash.auto import keccak


def _validate(value: Any) -> None:
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _validate(item)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _validate(item)
        return
    raise ValueError("canonical JSON requires JSON values and string object keys")


def canonical_json(value: Any) -> str:
    """Sorted keys recursively, compact separators, literal UTF-8 characters.

    This is the plan's Python JSON convention, not RFC 8785/JCS. ID and token
    amounts in cross-language records should remain strings as in types.py.
    """
    _validate(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def canonical_hash(value: Any) -> str:
    return "0x" + keccak(canonical_json(value).encode("utf-8")).hex()
