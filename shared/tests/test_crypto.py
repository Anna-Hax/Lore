import hashlib
import hmac

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from lore_shared.crypto import content_hash, decrypt_node, encrypt_node

KEY = bytes(range(32))


def test_ethereum_hash_vector():
    assert content_hash("") == "0xc5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    assert content_hash("research") != content_hash("research\n")


@pytest.mark.parametrize("text", ["", "A research node.", "研究 🧠\nनमस्ते", "a" * 50_000])
def test_round_trip(text):
    blob = encrypt_node(text, master_key=KEY)
    assert len(blob) == len(text.encode("utf-8")) + 28
    assert decrypt_node(blob, content_hash(text), master_key=KEY) == text


def test_independent_hkdf_and_blob_layout():
    text = "wire format fixture"
    # RFC 5869 extract + one expand block; independent of cryptography.HKDF.
    prk = hmac.new(bytes(32), KEY, hashlib.sha256).digest()
    info = ("lore-node:" + content_hash(text)).encode("ascii")
    key = hmac.new(prk, info + b"\x01", hashlib.sha256).digest()
    blob = encrypt_node(text, master_key=KEY)
    assert AESGCM(key).decrypt(blob[:12], blob[12:], None) == text.encode()


def test_iv_is_fresh():
    assert encrypt_node("same", master_key=KEY) != encrypt_node("same", master_key=KEY)


@pytest.mark.parametrize("index", [0, 12, -1])
def test_iv_ciphertext_and_tag_tampering_fail(index):
    blob = bytearray(encrypt_node("private research", master_key=KEY))
    blob[index] ^= 1
    with pytest.raises(InvalidTag):
        decrypt_node(bytes(blob), content_hash("private research"), master_key=KEY)


def test_wrong_key_or_hash_fails():
    blob = encrypt_node("private", master_key=KEY)
    with pytest.raises(InvalidTag):
        decrypt_node(blob, content_hash("private"), master_key=b"x" * 32)
    with pytest.raises(InvalidTag):
        decrypt_node(blob, content_hash("other"), master_key=KEY)


def test_even_authenticated_text_must_match_content_hash():
    expected = content_hash("original")
    prk = hmac.new(bytes(32), KEY, hashlib.sha256).digest()
    key = hmac.new(prk, ("lore-node:" + expected).encode() + b"\x01", hashlib.sha256).digest()
    iv = bytes(range(12))
    forged = iv + AESGCM(key).encrypt(iv, b"different text", None)
    with pytest.raises(InvalidTag):
        decrypt_node(forged, expected, master_key=KEY)


@pytest.mark.parametrize("blob", [b"", b"x" * 27])
def test_truncated_blob(blob):
    with pytest.raises(ValueError):
        decrypt_node(blob, content_hash(""), master_key=KEY)


def test_secrets_are_required_and_errors_do_not_echo_them(monkeypatch):
    monkeypatch.delenv("MASTER_KEY", raising=False)
    with pytest.raises(ValueError, match="MASTER_KEY"):
        encrypt_node("test")
    monkeypatch.setenv("MASTER_KEY", "not-a-real-secret")
    with pytest.raises(ValueError) as error:
        encrypt_node("test")
    assert "not-a-real-secret" not in str(error.value)
    monkeypatch.setenv("MASTER_KEY", KEY.hex())
    assert decrypt_node(encrypt_node("test"), content_hash("test")) == "test"


@pytest.mark.parametrize("key", [b"", b"x" * 16, b"x" * 33, "x" * 32])
def test_invalid_key_sizes(key):
    with pytest.raises(ValueError):
        encrypt_node("test", master_key=key)


@pytest.mark.parametrize("digest", ["", "0x12", "0x" + "g" * 64, 5])
def test_invalid_hashes(digest):
    with pytest.raises(ValueError):
        decrypt_node(b"x" * 30, digest, master_key=KEY)
