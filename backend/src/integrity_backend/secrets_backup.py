"""Passphrase-encrypted backup of the secrets folder (D-028).

Format: MAGIC | salt (16 bytes) | nonce (12 bytes) | AES-256-GCM ciphertext of a JSON map
{file name: base64 content}. The key comes from scrypt(passphrase, salt). MAGIC is also the
associated data, so a file with another format or version fails to decrypt.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"IMS-SECRETS-BACKUP-v1\n"
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**15, 8, 1
MIN_PASSPHRASE_CHARS = 12


class BackupError(RuntimeError):
    pass


def _key(passphrase: str, salt: bytes) -> bytes:
    if len(passphrase) < MIN_PASSPHRASE_CHARS:
        raise BackupError(f"passphrase must have at least {MIN_PASSPHRASE_CHARS} characters")
    return Scrypt(salt=salt, length=32, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P).derive(passphrase.encode("utf-8"))


def pack(folder: Path, passphrase: str) -> bytes:
    """Encrypt every regular file directly in folder (README.md excluded)."""
    files = {p.name: base64.b64encode(p.read_bytes()).decode("ascii")
             for p in sorted(folder.iterdir()) if p.is_file() and p.name != "README.md"}
    if not files:
        raise BackupError(f"no secret files in {folder}")
    salt, nonce = os.urandom(16), os.urandom(12)
    plaintext = json.dumps(files, sort_keys=True).encode("utf-8")
    return MAGIC + salt + nonce + AESGCM(_key(passphrase, salt)).encrypt(nonce, plaintext, MAGIC)


def unpack(blob: bytes, passphrase: str) -> dict[str, bytes]:
    if not blob.startswith(MAGIC):
        raise BackupError("not a secrets backup (or an unknown version)")
    body = blob[len(MAGIC):]
    salt, nonce, ciphertext = body[:16], body[16:28], body[28:]
    try:
        plaintext = AESGCM(_key(passphrase, salt)).decrypt(nonce, ciphertext, MAGIC)
    except InvalidTag as err:
        raise BackupError("wrong passphrase or damaged backup") from err
    return {name: base64.b64decode(content) for name, content in json.loads(plaintext).items()}


def restore(blob: bytes, passphrase: str, folder: Path) -> list[Path]:
    """Write the backed-up files into folder. Refuses to overwrite an existing file."""
    files = unpack(blob, passphrase)
    clashes = [name for name in files if (folder / name).exists()]
    if clashes:
        raise BackupError(f"refusing to overwrite existing files: {', '.join(sorted(clashes))}")
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for name, content in files.items():
        if Path(name).name != name:
            raise BackupError(f"unsafe file name in backup: {name!r}")
        (folder / name).write_bytes(content)
        written.append(folder / name)
    return written
