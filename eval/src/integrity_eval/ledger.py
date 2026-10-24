"""Test-access ledger (SPEC 12.3): every computation on test subjects appends one JSON line.

Reports print the ledger. More than one "final" entry for the same purpose has to be explained.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .manifest import REPO_ROOT, run_manifest


def ledger_path(repo_root: Path = REPO_ROOT) -> Path:
    cfg = yaml.safe_load((repo_root / "config" / "eval.yaml").read_text(encoding="utf-8"))
    return repo_root / cfg["test_ledger"]


def record_test_access(purpose: str, dataset_id: str, n_test_subjects: int, final: bool, seed: int,
                       extra: dict[str, Any] | None = None, path: Path | None = None) -> dict[str, Any]:
    m = run_manifest(seed, (dataset_id,), synthetic=False)
    entry = {
        "time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "purpose": purpose, "dataset": dataset_id, "n_test_subjects": n_test_subjects, "final": final,
        "git_commit": m.git_commit, "git_dirty": m.git_dirty, "config_sha256": m.config_sha256, "seed": seed,
        **(extra or {}),
    }
    target = path or ledger_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def read_ledger(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or ledger_path()
    if not target.exists():
        return []
    return [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]
