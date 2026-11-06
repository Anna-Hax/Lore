"""AES-256-GCM content blobs: 12-byte IV || ciphertext || 16-byte tag.

Only the gateway may hold MASTER_KEY. Authorization belongs at its endpoints;
these low-level functions do not establish a caller's right to read content.
"""

import hmac
import os
import re

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from eth_hash.auto import keccak

from ._secrets import secret_bytes


def content_hash(plaintext: str) -> str:
    """Ethereum Keccak-256 of the exact UTF-8 text, including whitespace."""
    return "0x" + keccak(plaintext.encode("utf-8")).hex()


def _node_key(digest: str, master_key: bytes | None) -> bytes:
    if not isinstance(digest, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", digest):
        raise ValueError("content hash must be a 0x-prefixed bytes32")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=("lore-node:" + digest.lower()).encode("ascii"),
    ).derive(secret_bytes(master_key, "MASTER_KEY"))


def encrypt_node(plaintext: str, *, master_key: bytes | None = None) -> bytes:
    key = _node_key(content_hash(plaintext), master_key)
    iv = os.urandom(12)
    return iv + AESGCM(key).encrypt(iv, plaintext.encode("utf-8"), None)


def decrypt_node(
    blob: bytes, expected_content_hash: str, *, master_key: bytes | None = None
) -> str:
    key = _node_key(expected_content_hash, master_key)
    if not isinstance(blob, bytes) or len(blob) < 28:
        raise ValueError("encrypted node must include a 12-byte IV and 16-byte tag")
    plaintext = AESGCM(key).decrypt(blob[:12], blob[12:], None).decode("utf-8")
    if not hmac.compare_digest(content_hash(plaintext), expected_content_hash.lower()):
        raise InvalidTag("decrypted node does not match its content hash")
    return plaintext
