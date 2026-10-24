"""Back up or restore the secrets folder as one passphrase-encrypted file (D-028).

Keep the backup offline (for example a USB drive kept by the named key holder) and the
passphrase in a password manager, never next to the file. Without the field key
(data_key.bin), encrypted event payloads cannot be read.

Usage:
  python scripts/backup_secrets.py backup  E:\\integrity-secrets-2026-10-24.bak
  python scripts/backup_secrets.py restore E:\\integrity-secrets-2026-10-24.bak
  python scripts/backup_secrets.py verify  E:\\integrity-secrets-2026-10-24.bak
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from integrity_backend.guard import SecretsDirError, check_secrets_dir
from integrity_backend.secrets_backup import BackupError, pack, restore, unpack
from integrity_backend.settings import REPO_ROOT, load_config, resolve_secrets_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Encrypted backup of the secrets folder (D-028).")
    parser.add_argument("action", choices=["backup", "restore", "verify"])
    parser.add_argument("file", type=Path)
    args = parser.parse_args(argv)
    try:
        folder = resolve_secrets_dir()
        if args.action == "backup":
            # Same location rule as the secrets themselves: not in the repo, not in a synced folder.
            check_secrets_dir(args.file.resolve().parent, REPO_ROOT, load_config("privacy")["forbidden_data_root_markers"])
            passphrase = getpass.getpass("New backup passphrase (12+ characters): ")
            if getpass.getpass("Repeat it: ") != passphrase:
                raise BackupError("passphrases differ")
            args.file.write_bytes(pack(folder, passphrase))
            print(f"wrote {args.file}. Verify it now: python scripts/backup_secrets.py verify {args.file}")
        elif args.action == "verify":
            names = sorted(unpack(args.file.read_bytes(), getpass.getpass("Backup passphrase: ")))
            print("backup OK: " + ", ".join(names))
        else:
            for path in restore(args.file.read_bytes(), getpass.getpass("Backup passphrase: "), folder):
                print(f"restored {path}")
    except (BackupError, SecretsDirError, OSError) as err:
        print(f"backup_secrets: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
