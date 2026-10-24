"""Create local development secrets. Never overwrites an existing file.

They go to INTEGRITY_SECRETS_DIR, or ~/.integrity-exam/secrets by default: outside the repository
and outside any cloud-synced folder (D-028). Back them up with scripts/backup_secrets.py.

Usage: python scripts/make_secrets.py
"""

from __future__ import annotations

import secrets
from pathlib import Path

from integrity_backend.settings import resolve_secrets_dir


def write_once(folder: Path, name: str, content: bytes) -> None:
    path = folder / name
    if path.exists():
        print(f"kept    {path}")
        return
    path.write_bytes(content)
    print(f"created {path}")


def main() -> None:
    folder = resolve_secrets_dir()
    folder.mkdir(parents=True, exist_ok=True)
    write_once(folder, "pg_password.txt", secrets.token_urlsafe(24).encode())
    write_once(folder, "data_key.bin", secrets.token_bytes(32))          # AES-256-GCM field key
    write_once(folder, "reviewer_token.txt", secrets.token_urlsafe(32).encode())
    write_once(folder, "admin_token.txt", secrets.token_urlsafe(32).encode())


if __name__ == "__main__":
    main()
