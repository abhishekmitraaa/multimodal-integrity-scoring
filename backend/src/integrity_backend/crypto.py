"""Application-level field encryption at rest (SPEC 10.6, D-006): AES-256-GCM."""

from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_VERSION = b"\x01"
_NONCE_BYTES = 12


class FieldCipher:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("AES-256-GCM needs a 32-byte key")
        self._aead = AESGCM(key)

    def encrypt(self, plaintext: bytes, aad: bytes) -> bytes:
        nonce = os.urandom(_NONCE_BYTES)
        return _VERSION + nonce + self._aead.encrypt(nonce, plaintext, aad)

    def decrypt(self, blob: bytes, aad: bytes) -> bytes:
        if blob[:1] != _VERSION:
            raise ValueError("unknown ciphertext version")
        nonce = blob[1 : 1 + _NONCE_BYTES]
        return self._aead.decrypt(nonce, blob[1 + _NONCE_BYTES :], aad)


def event_aad(session_id: str, server_seq: int) -> bytes:
    """Binds a ciphertext to its row, so moving it to another row fails to decrypt."""
    return f"event:{session_id}:{server_seq}".encode("ascii")
