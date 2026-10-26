"""The installed serving model (data folder, outside the repo). Skipped where it is not installed."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("torch")

from integrity_backend.app import load_keystroke_model, report_config  # noqa: E402

DATA_ROOT = Path(os.environ.get("INTEGRITY_DATA_ROOT", r"C:\integrity-data"))
MODEL_FILE = report_config()["report"]["model_file"]


@pytest.mark.skipif(not (DATA_ROOT / MODEL_FILE).exists(), reason="serving model not installed in the data root")
def test_installed_model_embeds_and_has_sane_reference_ranges() -> None:
    model, note = load_keystroke_model(DATA_ROOT, MODEL_FILE)
    assert model is not None, note
    assert "validation" in note
    rng = np.random.default_rng(0)
    windows = [np.column_stack([rng.integers(65, 91, 70) / 255, rng.uniform(0.05, 0.15, (70, 4))]).astype(np.float32) for _ in range(3)]
    emb = model.embed(windows)
    assert emb.shape == (3, 128) and np.all(np.isfinite(emb))
    for g in (1, 5, 10, 25):
        ref = model.reference(g)
        assert ref.genuine["p50"] < ref.genuine["p95"] and ref.eer_threshold > 0
    assert model.reference(25).g == 10          # G above the calibrated range uses the largest G


def test_missing_model_is_reported(tmp_path: Path) -> None:
    model, note = load_keystroke_model(tmp_path, MODEL_FILE)
    assert model is None and "No keystroke model" in note
