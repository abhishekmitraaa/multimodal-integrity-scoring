"""EWMA smoothing and its time-to-detection cost (SPEC 8.3). Inputs are SYNTHETIC numbers."""

from __future__ import annotations

import itertools

import numpy as np
import pytest
from scipy.special import expit, logit

from integrity_ml.smoothing import ewma_logit, isolated_dip_threshold, ticks_to_cross


def simulate_ticks(l0: float, l1: float, theta: float, lam: float, max_ticks: int = 10_000) -> int | None:
    state = l0
    if state < theta:
        return 0
    for k in range(1, max_ticks + 1):
        state = lam * l1 + (1 - lam) * state
        if state < theta:
            return k
    return None


@pytest.mark.parametrize(
    "l0,l1,theta,lam",
    list(itertools.product([0.5, 2.0, 4.0], [-3.0, -0.5, -0.01], [0.0], [0.1, 0.3, 0.5, 0.8, 1.0])),
)
def test_closed_form_matches_simulation(l0: float, l1: float, theta: float, lam: float) -> None:
    assert ticks_to_cross(l0, l1, theta, lam) == simulate_ticks(l0, l1, theta, lam)


def test_no_smoothing_detects_on_first_tick() -> None:
    assert ticks_to_cross(3.0, -0.1, 0.0, 1.0) == 1


def test_worked_example_in_spec() -> None:
    # SPEC 8.3: lam = 0.5, score sits 2 logits above threshold, attack holds it 0.5 below -> 3 ticks.
    assert ticks_to_cross(2.0, -0.5, 0.0, 0.5) == 3


def test_more_smoothing_never_detects_sooner() -> None:
    delays = [ticks_to_cross(2.0, -0.5, 0.0, lam) for lam in (1.0, 0.8, 0.5, 0.3, 0.1)]
    assert all(d is not None for d in delays)
    assert delays == sorted(delays)  # type: ignore[type-var]


def test_never_crosses_if_attack_stays_above_threshold() -> None:
    assert ticks_to_cross(2.0, 0.1, 0.0, 0.5) is None


def test_isolated_dip_threshold_matches_one_step() -> None:
    l0, theta, lam = 2.0, 0.0, 0.5
    cut = isolated_dip_threshold(l0, theta, lam)
    assert cut == pytest.approx(-2.0)
    assert lam * (cut - 1e-9) + (1 - lam) * l0 < theta
    assert lam * (cut + 1e-9) + (1 - lam) * l0 >= theta


def test_ewma_first_value_unsmoothed_and_lam_one_is_identity() -> None:
    s = np.array([0.9, 0.2, 0.2, 0.8])
    assert ewma_logit(s, 0.5)[0] == pytest.approx(0.9)
    np.testing.assert_allclose(ewma_logit(s, 1.0), s)


def test_ewma_recurrence() -> None:
    s = np.array([0.9, 0.1, 0.3])
    out = logit(ewma_logit(s, 0.5))
    raw = logit(s)
    assert out[1] == pytest.approx(0.5 * raw[1] + 0.5 * raw[0])
    assert out[2] == pytest.approx(0.5 * raw[2] + 0.5 * out[1])
    assert expit(out[0]) == pytest.approx(0.9)
