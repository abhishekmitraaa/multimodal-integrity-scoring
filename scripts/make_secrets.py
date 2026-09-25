"""Create local development secrets in secrets/ (git-ignored). Never overwrites an existing file.

Usage: python scripts/make_secrets.py
"""

from __future__ import annotations

import secrets
from pathlib import Path

SECRETS = Path(__file__).resolve().parents[1] / "secrets"


def write_once(name: str, content: bytes) -> None:
    path = SECRETS / name
    if path.exists():
        print(f"kept    {name}")
        return
    path.write_bytes(content)
    print(f"created {name}")


def main() -> None:
    SECRETS.mkdir(exist_ok=True)
    write_once("pg_password.txt", secrets.token_urlsafe(24).encode())
    write_once("data_key.bin", secrets.token_bytes(32))          # AES-256-GCM field key
    write_once("reviewer_token.txt", secrets.token_urlsafe(32).encode())
    write_once("admin_token.txt", secrets.token_urlsafe(32).encode())


if __name__ == "__main__":
    main()
