"""TypeNet protocol runner and the synthetic pipeline check (SYNTHETIC data only)."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pytest
import yaml

from integrity_eval.authentication import DigraphScorer, SeqStatScorer, run_authentication
from integrity_eval.manifest import config_sha256, run_manifest
from integrity_eval.p2_synthetic import main, render, run
from integrity_ml.baselines import pooled_within_subject_mad, sequence_stats
from integrity_ml.keystroke import Keystroke
from integrity_ml.synthetic_keystrokes import SyntheticConfig, generate

REPO = Path(__file__).resolve().parents[2]
SYN = yaml.safe_load((REPO / "config" / "eval.yaml").read_text(encoding="utf-8"))["synthetic_keystrokes"]
GEN, IMP = [10, 11, 12, 13, 14], 11


class CountingScorer:
    """Distance = |query id - subject id|: subject i's own sequences score 0."""

    name = "counting"

    def __init__(self) -> None:
        self.calls = 0

    def prepare(self, seq: Sequence[Keystroke]) -> int:
        return seq[0].down_us   # the subject id is stored here by _toy

    def gallery(self, seqs: Sequence[Sequence[Keystroke]], prepared: Sequence[int]) -> int:
        return prepared[0]

    def distance(self, gallery: int, query: int) -> float | None:
        self.calls += 1
        return float(abs(gallery - query))


def _toy(n: int) -> list[list[list[Keystroke]]]:
    return [[[Keystroke("KeyA", i, i + 1)] for _ in range(15)] for i in range(n)]


def test_protocol_counts_and_perfect_scorer() -> None:
    scorer = CountingScorer()
    r = run_authentication(_toy(6), scorer, g=5, genuine_idx=GEN, impostor_idx=IMP, steps=10_000)
    assert scorer.calls == 6 * (5 + 5)        # per subject: 5 genuine + (k - 1) impostor queries
    assert r.per_subject.mean == 0.0 and r.global_eer == 0.0
    assert (r.genuine_available, r.impostor_available, r.subjects_without_scores) == (1.0, 1.0, 0)


def test_protocol_rejects_gallery_overlapping_queries() -> None:
    with pytest.raises(ValueError, match="overlaps"):
        run_authentication(_toy(3), CountingScorer(), g=11, genuine_idx=GEN, impostor_idx=IMP, steps=100)


def test_unavailable_scores_are_dropped_and_counted() -> None:
    data = generate(SyntheticConfig.from_config(SYN, separation=1.0, seed=3, subjects=8))
    strict = DigraphScorer(min_occurrences=3, min_shared_items=10_000)   # never enough shared items
    r = run_authentication(data.subjects, strict, g=1, genuine_idx=GEN, impostor_idx=IMP, steps=1000)
    assert (r.genuine_available, r.impostor_available, r.subjects_without_scores) == (0.0, 0.0, 8)


def test_separable_synthetic_subjects_give_low_eer_and_identical_ones_about_half() -> None:
    def eer(separation: float) -> float:
        data = generate(SyntheticConfig.from_config(SYN, separation=separation, seed=11, subjects=40))
        train, test = data.subjects[:15], data.subjects[15:]
        scale = pooled_within_subject_mad([[sequence_stats(s) for s in subj] for subj in train])
        return run_authentication(test, SeqStatScorer(scale), g=10, genuine_idx=GEN, impostor_idx=IMP, steps=10_000).per_subject.mean

    assert 0.35 < eer(0.0) < 0.65
    assert eer(1.5) < eer(0.0) - 0.2


def test_report_is_watermarked_and_carries_a_manifest(tmp_path: Path) -> None:
    results, info = run(subjects=12)
    report = render(results, info)
    assert "SYNTHETIC — NOT A RESULT" in report
    assert config_sha256() in report and "synthetic: `True`" in report
    assert main(["--subjects", "12", "--out", str(tmp_path / "r.md")]) == 0
    assert "SYNTHETIC" in (tmp_path / "r.md").read_text(encoding="utf-8")


def test_manifest_fields() -> None:
    m = run_manifest(1, ("x",), synthetic=True)
    assert len(m.config_sha256) == 64 and m.seed == 1 and m.synthetic is True
