"""EER on hand-built SYNTHETIC scores, including a direct port of the authors' published loop."""

from __future__ import annotations

import numpy as np
import pytest

from integrity_ml.eer import eer_exact, eer_sweep, summarise


def authors_eer_compute(scores_g: np.ndarray, scores_i: np.ndarray) -> float:
    """The README's eer_compute, transcribed (it returns accuracy = 100 - EER in %)."""
    far, frr = [], []
    ini = min(np.concatenate((scores_g, scores_i)))
    fin = max(np.concatenate((scores_g, scores_i)))
    paso = (fin - ini) / 10000
    threshold = ini - paso
    while threshold < fin + paso:
        far.append(len(np.where(scores_i >= threshold)[0]) / len(scores_i))
        frr.append(len(np.where(scores_g < threshold)[0]) / len(scores_g))
        threshold = threshold + paso
    gap = abs(np.asarray(far) - np.asarray(frr))
    j = np.where(gap == min(gap))[0]
    index = j[0]
    return ((far[index] + frr[index]) / 2) * 100


def test_perfect_separation_is_zero() -> None:
    assert eer_sweep([0.1, 0.2, 0.3], [0.8, 0.9, 1.0]) == 0.0
    assert eer_exact([0.1, 0.2, 0.3], [0.8, 0.9, 1.0]) == 0.0


def test_fully_reversed_is_one() -> None:
    assert eer_exact([0.9, 1.0], [0.1, 0.2]) == pytest.approx(1.0)


def test_hand_computed_overlap() -> None:
    # Genuine {1,2,3,4}, impostor {3.5,5,6,7}: at threshold 4 FAR = 1/4, FRR = 1/4.
    assert eer_exact([1, 2, 3, 4], [3.5, 5, 6, 7]) == pytest.approx(0.25)


def test_identical_scores_are_half() -> None:
    assert eer_sweep([1.0, 1.0], [1.0, 1.0]) == 0.5


@pytest.mark.parametrize("seed", range(10))
def test_sweep_matches_the_authors_code(seed: int) -> None:
    rng = np.random.default_rng(seed)
    g = rng.normal(1.0, 0.4, size=5)       # 5 genuine scores per subject, as in TypeNet
    imp = rng.normal(2.0, 0.5, size=999)   # k - 1 impostor scores
    assert eer_sweep(g, imp) * 100 == pytest.approx(100 - authors_eer_compute(g, imp), abs=1e-9)


def test_rejects_empty_and_non_finite() -> None:
    with pytest.raises(ValueError):
        eer_sweep([], [1.0])
    with pytest.raises(ValueError):
        eer_exact([float("nan")], [1.0])


def test_summary() -> None:
    s = summarise([0.0, 0.2])
    assert (s.mean, s.sd, s.n_subjects) == (pytest.approx(0.1), pytest.approx(0.1), 2)
