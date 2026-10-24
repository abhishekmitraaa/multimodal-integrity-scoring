"""Non-deep baselines and the synthetic generator, on hand-built and generated SYNTHETIC data."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml

from integrity_ml.baselines import (
    digraph_distance, digraph_profile, pooled_within_subject_mad, seqstat_distance, sequence_stats,
)
from integrity_ml.keystroke import Keystroke, latencies
from integrity_ml.synthetic_keystrokes import SyntheticConfig, generate

SYN = yaml.safe_load((Path(__file__).resolve().parents[2] / "config" / "eval.yaml").read_text(encoding="utf-8"))["synthetic_keystrokes"]


def seq(codes: str, flight_ms: float, hold_ms: float) -> list[Keystroke]:
    return [Keystroke(c, round(i * flight_ms * 1000), round((i * flight_ms + hold_ms) * 1000)) for i, c in enumerate(codes)]


def test_digraph_profile_keeps_only_frequent_items() -> None:
    p = digraph_profile([seq("abab", 100, 50), seq("abc", 120, 60)], min_occurrences=3)
    assert p.digraph_pl_ms == {("a", "b"): pytest.approx(100.0)}   # a→b seen 3 times: 100, 100, 120
    assert p.key_hl_ms == {"a": pytest.approx(50.0), "b": pytest.approx(50.0)}   # c seen once


def test_digraph_distance_is_mean_over_shared_items() -> None:
    gallery = digraph_profile([seq("ab", 100, 50)], min_occurrences=1)
    query = digraph_profile([seq("ab", 130, 40)], min_occurrences=1)
    # shared: a→b (|100-130| = 30), a (10), b (10) → mean 50/3
    assert digraph_distance(gallery, query, min_shared_items=3) == pytest.approx(50 / 3)
    assert digraph_distance(gallery, query, min_shared_items=4) is None


def test_sequence_stats_values() -> None:
    stats = sequence_stats(seq("abc", 100, 150))   # holds 150, flights 100 → IL = -50
    assert stats[:2].tolist() == [150.0, 0.0]
    assert stats[2:4].tolist() == [100.0, 0.0]
    assert stats[4:6].tolist() == [-50.0, 0.0]
    assert np.all(np.isnan(sequence_stats(seq("a", 100, 50))[2:]))


def test_scale_and_distance() -> None:
    a = [np.array([1.0, 1.0]), np.array([3.0, 5.0])]          # deviations 1,2 / 1,2
    b = [np.array([10.0, 10.0]), np.array([10.0, 10.0])]      # deviations 0
    scale = pooled_within_subject_mad([a, b])
    assert scale.tolist() == [0.5, 1.0]
    assert seqstat_distance(a, np.array([2.5, 4.0]), scale) == pytest.approx((0.5 / 0.5 + 1.0 / 1.0) / 2)
    with pytest.raises(ValueError):
        pooled_within_subject_mad([b])


def _cfg(separation: float, subjects: int = 6) -> SyntheticConfig:
    return SyntheticConfig.from_config(SYN, separation=separation, seed=7, subjects=subjects)


def test_synthetic_data_is_labelled_reproducible_and_shaped() -> None:
    a, b = generate(_cfg(1.0)), generate(_cfg(1.0))
    assert a.synthetic is True and a.config.dataset_id.startswith("d3_synthetic")
    assert a.subjects == b.subjects
    assert len(a.subjects) == 6 and all(len(s) == SYN["sequences_per_subject"] for s in a.subjects)
    assert all(len(q) == SYN["keys_per_sequence"] for s in a.subjects for q in s)
    assert generate(SyntheticConfig.from_config(SYN, separation=1.0, seed=8, subjects=6)).subjects != a.subjects


def test_synthetic_timing_is_plausible_and_has_overlaps() -> None:
    stats = np.vstack([sequence_stats(q) for s in generate(_cfg(1.0)).subjects for q in s])
    assert 60 < np.median(stats[:, 0]) < 160       # hold mean, ms
    assert 100 < np.median(stats[:, 2]) < 400      # press-to-press mean, ms
    overlap = [float((latencies(q).il_ms < 0).mean()) for s in generate(_cfg(1.0)).subjects for q in s]
    assert 0.0 < float(np.mean(overlap)) < 0.5     # some keys overlap, most do not


def test_zero_separation_makes_subjects_indistinguishable() -> None:
    data = generate(_cfg(0.0, subjects=20))
    means = np.array([np.mean([sequence_stats(q)[2] for q in s]) for s in data.subjects])
    spread_between = means.std()
    spread_within = np.mean([np.std([sequence_stats(q)[2] for q in s]) for s in data.subjects])
    assert spread_between < spread_within          # subject means differ only by noise
