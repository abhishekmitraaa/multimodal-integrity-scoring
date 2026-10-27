"""Fusion weights on distance inputs are constrained non-positive (SPEC 7.4).

All data here is SYNTHETIC, generated from seeded RNGs with a known orientation.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray
from sklearn.linear_model import LogisticRegression

from integrity_ml.fusion import FusionModel, WeightSignError, assert_weight_signs, fit_fusion

NAMES = ("d_ks", "d_proc", "ks_available")
MASK = (True, True, False)


def synthetic_well_oriented(seed: int, n: int = 400) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """SYNTHETIC: attacks (y=0) have larger distances; availability is uninformative noise."""
    rng = np.random.default_rng(seed)
    y = rng.integers(0, 2, n).astype(np.float64)
    d_ks = rng.normal(1.0 - 0.8 * y, 0.5)
    d_proc = rng.normal(1.0 - 0.5 * y, 0.5)
    avail = rng.integers(0, 2, n).astype(np.float64)
    return np.column_stack([d_ks, d_proc, avail]), y


def synthetic_misoriented(seed: int, n: int = 400) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """SYNTHETIC: d_proc is *higher* for genuine sessions, so an unconstrained fit wants w > 0."""
    rng = np.random.default_rng(seed)
    y = rng.integers(0, 2, n).astype(np.float64)
    d_ks = rng.normal(1.0 - 0.8 * y, 0.5)
    d_proc = rng.normal(0.5 + 0.8 * y, 0.5)
    avail = (rng.random(n) < 0.3 + 0.4 * y).astype(np.float64)  # genuine more often available
    return np.column_stack([d_ks, d_proc, avail]), y


def standardise(x: NDArray[np.float64]) -> NDArray[np.float64]:
    sd = x.std(axis=0)
    sd[sd == 0] = 1.0
    return np.asarray((x - x.mean(axis=0)) / sd, dtype=np.float64)


def test_fusion_weights_negative_on_well_oriented_data() -> None:
    x, y = synthetic_well_oriented(seed=1)
    model = fit_fusion(x, y, NAMES, MASK)
    assert model.coef[0] < 0 and model.coef[1] < 0


def test_distance_weight_is_clamped_when_data_pulls_it_positive() -> None:
    x, y = synthetic_misoriented(seed=2)
    unconstrained = LogisticRegression(C=1.0, max_iter=10_000).fit(standardise(x), y)
    assert unconstrained.coef_[0][1] > 0.1, "precondition: an unconstrained fit goes positive"

    model = fit_fusion(x, y, NAMES, MASK)
    assert model.coef[1] <= 0.0
    assert model.coef[1] == pytest.approx(0.0, abs=1e-8)  # sits on the bound
    assert model.coef[0] < 0


def test_non_distance_inputs_are_unconstrained() -> None:
    x, y = synthetic_misoriented(seed=3)
    model = fit_fusion(x, y, NAMES, MASK)
    assert model.coef[2] > 0  # availability indicator may take either sign


def test_matches_sklearn_when_constraints_are_inactive() -> None:
    x, y = synthetic_well_oriented(seed=4)
    model = fit_fusion(x, y, NAMES, MASK, c=0.7)
    reference = LogisticRegression(C=0.7, max_iter=10_000, tol=1e-12).fit(standardise(x), y)
    np.testing.assert_allclose(model.coef, reference.coef_[0], atol=1e-4)
    assert model.intercept == pytest.approx(reference.intercept_[0], abs=1e-4)


@pytest.mark.parametrize("seed", range(20))
def test_distance_weights_never_positive_on_random_synthetic_data(seed: int) -> None:
    rng = np.random.default_rng(100 + seed)
    n, d = 200, 5
    x = rng.normal(size=(n, d))
    y = (rng.random(n) < 0.5).astype(np.float64)
    x[:, :3] += rng.normal(size=3) * y[:, None]  # random, possibly wrong-way, associations
    mask = (True, True, True, False, False)
    model = fit_fusion(x, y, [f"x{i}" for i in range(d)], mask)
    assert np.all(model.coef[:3] <= 0.0)


def test_score_never_increases_with_a_distance_input() -> None:
    x, y = synthetic_misoriented(seed=5)
    model = fit_fusion(x, y, NAMES, MASK)
    rng = np.random.default_rng(6)
    base = rng.normal(size=(100, 3))
    for j in (0, 1):
        bumped = base.copy()
        bumped[:, j] += 1.0
        assert np.all(model.score(bumped) <= model.score(base) + 1e-12)


def test_score_is_in_unit_interval_and_high_means_genuine() -> None:
    x, y = synthetic_well_oriented(seed=7)
    model = fit_fusion(x, y, NAMES, MASK)
    s = model.score(x)
    assert np.all((s > 0) & (s < 1))
    assert s[y == 1].mean() > s[y == 0].mean()


def test_assert_weight_signs_rejects_positive_distance_weight() -> None:
    bad = FusionModel(
        feature_names=NAMES,
        distance_mask=MASK,
        mean=np.zeros(3),
        scale=np.ones(3),
        coef=np.array([-1.0, 0.2, 0.5]),
        intercept=0.0,
    )
    with pytest.raises(WeightSignError, match="d_proc"):
        assert_weight_signs(bad)


def test_rejects_bad_labels_and_shapes() -> None:
    x, y = synthetic_well_oriented(seed=8)
    with pytest.raises(ValueError):
        fit_fusion(x, y * 2, NAMES, MASK)
    with pytest.raises(ValueError):
        fit_fusion(x, y, NAMES[:2], MASK)


def test_a_precision_stop_at_the_optimum_is_accepted_but_a_real_failure_is_not(monkeypatch: Any) -> None:
    import integrity_ml.fusion as fu
    from scipy.optimize import minimize as real_minimize

    rng = np.random.default_rng(3)
    x = rng.normal(size=(200, 2))
    y = (x[:, 0] + rng.normal(size=200) < 0).astype(float)

    def precision_stop(*args: Any, **kw: Any) -> Any:          # optimal, but reported like L-BFGS-B's ABNORMAL
        r = real_minimize(*args, **kw)
        r.success, r.message = False, "ABNORMAL: "
        return r

    monkeypatch.setattr(fu, "minimize", precision_stop)
    model = fu.fit_fusion(x, y, ["d1", "d2"], [True, True])
    assert model.coef[0] < 0

    def gave_up(*args: Any, **kw: Any) -> Any:                  # stopped at the start: far from optimal
        r = real_minimize(*args, **{**kw, "options": {"maxiter": 0}})
        r.success, r.message = False, "STOP: TOTAL NO. OF ITERATIONS REACHED LIMIT"
        return r

    monkeypatch.setattr(fu, "minimize", gave_up)
    with pytest.raises(RuntimeError, match="did not converge"):
        fu.fit_fusion(x, y, ["d1", "d2"], [True, True])
