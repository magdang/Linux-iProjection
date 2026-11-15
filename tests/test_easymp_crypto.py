"""Legacy AES vectors cross-checked with Epson's seed routine and OpenSSL."""

import struct

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from linux_iprojection.easymp_crypto import EpsonAES, derive_key


@pytest.mark.parametrize("seed,key", [
    ("0000000000000000", "0000000000000000"),
    ("0102030405060708", "9261ed6526cd42db"),
    ("ffffffffffffffff", "77fb77fb77fb77fb"),
    ("123456789abcdef0", "ba5faa6e2c50de0b"),
])
def test_seed_derivation_matches_vendor_binary_vectors(seed, key):
    assert derive_key(bytes.fromhex(seed)) == bytes.fromhex(key * 2)


def test_envelope_matches_openssl_vector():
    cipher = EpsonAES(bytes(range(1, 9)))
    assert cipher.encrypt(b"abc").hex() == "58eb1f10c3f1cfbf5042f5e2e088c391273c1c28a0996f9081d3185932aa2230"


@pytest.mark.parametrize("size", [0, 1, 15, 16, 17, 65536])
def test_length_header_and_epson_padding(size):
    seed = bytes(range(1, 9))
    payload = bytes(range(256)) * (size // 256) + bytes(range(size % 256))
    encrypted = EpsonAES(seed).encrypt(payload)
    decoder = Cipher(algorithms.AES128(bytes.fromhex("9261ed6526cd42db" * 2)), modes.ECB()).decryptor()
    plain = decoder.update(encrypted) + decoder.finalize()
    padding = -size % 16
    assert plain[:16] == struct.pack(">I", size) + bytes(12)
    assert plain[16:16 + size] == payload
    assert plain[16 + size:] == bytes([padding]) * padding


def test_rejects_wrong_seed_size():
    with pytest.raises(ValueError, match="eight-byte"):
        derive_key(b"short")
