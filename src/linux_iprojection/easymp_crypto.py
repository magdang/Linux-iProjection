"""Legacy Epson AES framing; compatibility with the projector, not authenticated encryption."""

import struct

from .protocol import ProjectorError


def derive_key(seed: bytes) -> bytes:
    if len(seed) != 8:
        raise ValueError("EasyMP AES needs an eight-byte session seed")
    result = bytearray()
    for (state,) in struct.iter_unpack("<H", seed):
        output = 0
        for _ in range((state & 0xFFF) + 0xE8B):
            output = ((output << 1) | (state >> 16)) & 0xFFFF
            state = ((state << 1) | (((state >> 16) ^ (state >> 13)) & 1)) & 0x1FFFF
        result += struct.pack("<H", output)
    return bytes(result) * 2


class EpsonAES:
    def __init__(self, seed: bytes):
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        except ImportError as exc:
            raise ProjectorError("Native AES needs the optional cryptography dependency; install linux-iprojection[encryption]") from exc
        self._cipher = Cipher(algorithms.AES128(derive_key(seed)), modes.ECB())

    def encrypt(self, payload: bytes) -> bytes:
        padding = -len(payload) % 16
        block = struct.pack(">I", len(payload)) + bytes(12) + payload + bytes([padding]) * padding
        encryptor = self._cipher.encryptor()
        return encryptor.update(block) + encryptor.finalize()
