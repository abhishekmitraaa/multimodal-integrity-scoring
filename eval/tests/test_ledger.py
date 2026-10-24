"""Test-access ledger (SPEC 12.3)."""

from __future__ import annotations

from pathlib import Path

from integrity_eval.ledger import ledger_path, read_ledger, record_test_access


def test_entries_append_with_manifest(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    record_test_access("p2 baseline", "d1", 1000, final=False, seed=1, path=path)
    record_test_access("p2 encoder", "d1", 1000, final=True, seed=1, extra={"m": 70}, path=path)
    entries = read_ledger(path)
    assert [e["purpose"] for e in entries] == ["p2 baseline", "p2 encoder"]
    assert entries[1]["final"] is True and entries[1]["m"] == 70
    assert len(entries[0]["config_sha256"]) == 64 and entries[0]["git_commit"]


def test_default_path_is_the_git_ignored_ledger() -> None:
    assert ledger_path().as_posix().endswith("eval/ledger/test_access.jsonl")
    assert read_ledger(Path("does-not-exist.jsonl")) == []
