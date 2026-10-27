"""Application-level field encryption at rest (SPEC 10.6, D-006): AES-256-GCM."""

from __future__ import annotations

import hashlib
import hmac
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_VERSION = b"\x01"
_NONCE_BYTES = 12


class FieldCipher:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("AES-256-GCM needs a 32-byte key")
        self._aead = AESGCM(key)
        self._key = key

    def subkey(self, label: bytes) -> bytes:
        """A separate key for another purpose (HMAC-SHA256 of the label), so the field key itself is used only for AES-GCM."""
        return hmac.new(self._key, b"integrity-subkey:" + label, hashlib.sha256).digest()

    def keyed_ref(self, label: bytes, value: str) -> str:
        """A keyed reference to an identifier: unlinkable without the key, unlike a bare hash of a small space."""
        return hmac.new(self.subkey(label), value.encode("utf-8"), hashlib.sha256).hexdigest()

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
