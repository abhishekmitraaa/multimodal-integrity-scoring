"""Field encryption, data-root guard and ordering plan. All inputs SYNTHETIC."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from cryptography.exceptions import InvalidTag

from integrity_backend.crypto import FieldCipher, event_aad
from integrity_backend.guard import DataRootError, check_data_root
from integrity_backend.ingest import SessionState, plan_batch
from integrity_backend.wire import WireError

KEY = bytes(range(32))


def test_encrypt_roundtrip_and_ciphertext_hides_plaintext() -> None:
    cipher = FieldCipher(KEY)
    blob = cipher.encrypt(b'{"text":"def f(): pass"}', event_aad("s", 1))
    assert b"def f" not in blob
    assert cipher.decrypt(blob, event_aad("s", 1)) == b'{"text":"def f(): pass"}'


def test_ciphertext_bound_to_row() -> None:
    cipher = FieldCipher(KEY)
    blob = cipher.encrypt(b"payload", event_aad("s", 1))
    with pytest.raises(InvalidTag):
        cipher.decrypt(blob, event_aad("s", 2))


def test_tampered_ciphertext_rejected() -> None:
    cipher = FieldCipher(KEY)
    blob = bytearray(cipher.encrypt(b"payload", b"aad"))
    blob[-1] ^= 1
    with pytest.raises(InvalidTag):
        cipher.decrypt(bytes(blob), b"aad")


def test_key_length_enforced() -> None:
    with pytest.raises(ValueError):
        FieldCipher(b"short")


MARKERS = ["OneDrive", "Dropbox", "Google Drive", "iCloud"]


def test_data_root_accepts_outside_folder(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    root = check_data_root(tmp_path / "data", repo, MARKERS)
    assert root.is_dir()


@pytest.mark.parametrize(
    "rel",
    ["repo/data", "OneDrive/Desktop/data", "Users/x/Dropbox/d"],
)
def test_data_root_rejects_repo_and_sync_folders(tmp_path: Path, rel: str) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(DataRootError):
        check_data_root(tmp_path / rel, repo, MARKERS)


@pytest.mark.parametrize("raw", [None, "", "relative/path"])
def test_data_root_rejects_unset_or_relative(tmp_path: Path, raw: str | None) -> None:
    with pytest.raises(DataRootError):
        check_data_root(raw, tmp_path, MARKERS)


def synthetic_batch(first: int, n: int, epoch: int = 0) -> dict[str, Any]:
    return {"epoch": epoch, "events": [{"client_seq": first + i} for i in range(n)]}


STATE = SessionState(next_client_seq=10, next_server_seq=12, head=b"h", epoch=0)


def seqs(events: list[dict[str, Any]]) -> list[int]:
    return [e["client_seq"] for e in events]


def test_plan_accepts_expected_batch() -> None:
    plan = plan_batch(STATE, synthetic_batch(10, 3))
    assert seqs(plan.accept) == [10, 11, 12] and not plan.is_nack


def test_plan_drops_duplicate_prefix() -> None:
    plan = plan_batch(STATE, synthetic_batch(8, 5))
    assert seqs(plan.accept) == [10, 11, 12]


def test_plan_full_duplicate_is_empty_ack() -> None:
    plan = plan_batch(STATE, synthetic_batch(5, 3))
    assert plan.accept == [] and not plan.is_nack


def test_plan_gap_is_nack() -> None:
    plan = plan_batch(STATE, synthetic_batch(11, 2))
    assert plan.accept == [] and plan.resend_from == 10


def test_plan_wrong_epoch_rejected() -> None:
    with pytest.raises(WireError):
        plan_batch(STATE, synthetic_batch(10, 1, epoch=1))
