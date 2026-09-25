"""Synthetic data must be labelled in filenames and content (docs/SPEC.md section 10.11)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_DIRS = [ROOT / "shared" / "schema" / "examples", ROOT / "data" / "synthetic"]


def data_files() -> list[Path]:
    return [
        p
        for d in SYNTHETIC_DIRS
        if d.exists()
        for p in d.rglob("*")
        if p.is_file() and p.name != ".gitkeep"
    ]


def test_every_fixture_filename_says_synthetic() -> None:
    unlabelled = [p.name for p in data_files() if "synthetic" not in p.name.lower()]
    assert unlabelled == []


def test_every_fixture_segment_is_flagged_synthetic() -> None:
    for path in data_files():
        if path.suffix != ".json":
            continue
        batch = json.loads(path.read_text(encoding="utf-8"))
        for event in batch.get("events", []):
            if event["type"] == "segment_start":
                assert event["data"]["synthetic"] is True, path.name
