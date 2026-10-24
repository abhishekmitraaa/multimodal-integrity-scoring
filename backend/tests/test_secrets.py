"""Secrets folder location guard and encrypted backup (D-028). All keys here are random test keys."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from integrity_backend.guard import SecretsDirError, check_secrets_dir
from integrity_backend.secrets_backup import MAGIC, BackupError, pack, restore, unpack
from integrity_backend.settings import REPO_ROOT, resolve_secrets_dir

MARKERS = ["OneDrive", "Dropbox", "Google Drive", "iCloud"]
PASS = "correct horse battery"


def test_secrets_dir_outside_repo_and_sync_is_accepted(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    assert check_secrets_dir(tmp_path / "keys", repo, MARKERS) == (tmp_path / "keys").resolve()


@pytest.mark.parametrize("rel", ["repo/secrets", "Users/x/OneDrive/keys", "Dropbox/keys"])
def test_secrets_dir_inside_repo_or_sync_is_refused(tmp_path: Path, rel: str) -> None:
    with pytest.raises(SecretsDirError):
        check_secrets_dir(tmp_path / rel, tmp_path / "repo", MARKERS)


def test_relative_secrets_dir_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SecretsDirError):
        check_secrets_dir(Path("secrets"), tmp_path, MARKERS)


def test_resolve_refuses_the_old_in_repo_location() -> None:
    with pytest.raises(SecretsDirError, match="inside the repository"):
        resolve_secrets_dir({"INTEGRITY_SECRETS_DIR": str(REPO_ROOT / "secrets")})


def test_resolve_honours_the_environment(tmp_path: Path) -> None:
    assert resolve_secrets_dir({"INTEGRITY_SECRETS_DIR": str(tmp_path)}) == tmp_path.resolve()


def _secrets(folder: Path) -> dict[str, bytes]:
    folder.mkdir()
    files = {"data_key.bin": os.urandom(32), "pg_password.txt": b"pw", "README.md": b"not a secret"}
    for name, content in files.items():
        (folder / name).write_bytes(content)
    return files


def test_backup_round_trip(tmp_path: Path) -> None:
    files = _secrets(tmp_path / "src")
    blob = pack(tmp_path / "src", PASS)
    assert blob.startswith(MAGIC)
    assert files["data_key.bin"] not in blob
    assert unpack(blob, PASS) == {k: v for k, v in files.items() if k != "README.md"}
    restored = restore(blob, PASS, tmp_path / "dest")
    assert {p.name for p in restored} == {"data_key.bin", "pg_password.txt"}
    assert (tmp_path / "dest" / "data_key.bin").read_bytes() == files["data_key.bin"]


def test_backup_rejects_wrong_passphrase_tampering_and_overwrite(tmp_path: Path) -> None:
    _secrets(tmp_path / "src")
    blob = pack(tmp_path / "src", PASS)
    with pytest.raises(BackupError, match="wrong passphrase"):
        unpack(blob, PASS + "x")
    tampered = blob[:-1] + bytes([blob[-1] ^ 1])
    with pytest.raises(BackupError, match="wrong passphrase or damaged"):
        unpack(tampered, PASS)
    with pytest.raises(BackupError, match="not a secrets backup"):
        unpack(b"junk" + blob, PASS)
    with pytest.raises(BackupError, match="refusing to overwrite"):
        restore(blob, PASS, tmp_path / "src")


def test_write_secret_never_overwrites(tmp_path: Path) -> None:
    from integrity_backend.secrets_backup import write_secret

    write_secret(tmp_path / "k", b"one")
    with pytest.raises(FileExistsError):
        write_secret(tmp_path / "k", b"two")
    assert (tmp_path / "k").read_bytes() == b"one"
    if os.name == "posix":
        assert (tmp_path / "k").stat().st_mode & 0o777 == 0o600


def test_backup_needs_a_long_passphrase(tmp_path: Path) -> None:
    _secrets(tmp_path / "src")
    with pytest.raises(BackupError, match="at least"):
        pack(tmp_path / "src", "short")
