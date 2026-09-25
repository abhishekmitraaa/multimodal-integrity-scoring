"""Sign-constrained logistic-regression fusion (docs/SPEC.md section 7.4).

S = sigmoid(b + w . z), where z is the standardised input vector and label 1 = genuine.
Inputs marked as distances (higher = more anomalous) have their weights constrained to w <= 0
during optimisation, so more anomaly can never raise S. Standardisation divides by a positive
scale, so the sign constraint on z carries over to the raw inputs.

The objective matches scikit-learn's L2 LogisticRegression with the lbfgs solver:
    C * sum_i logloss_i + 0.5 * ||w||^2      (intercept not penalised)
so with inactive constraints the two give the same fit (tested).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.optimize import minimize
from scipy.special import expit, log_expit

FloatArray = NDArray[np.float64]


class WeightSignError(ValueError):
    """A distance input has a positive weight, so more anomaly would raise S."""


@dataclass(frozen=True)
class FusionModel:
    feature_names: tuple[str, ...]
    distance_mask: tuple[bool, ...]
    mean: FloatArray
    scale: FloatArray
    coef: FloatArray
    intercept: float

    def decision(self, x: ArrayLike) -> FloatArray:
        z = (np.asarray(x, dtype=np.float64) - self.mean) / self.scale
        return np.asarray(z @ self.coef + self.intercept, dtype=np.float64)

    def score(self, x: ArrayLike) -> FloatArray:
        """Integrity score S in (0, 1); high = genuine."""
        return np.asarray(expit(self.decision(x)), dtype=np.float64)


def fit_fusion(
    x: ArrayLike,
    y: ArrayLike,
    feature_names: Sequence[str],
    distance_mask: Sequence[bool],
    c: float = 1.0,
) -> FusionModel:
    """Fit S = sigmoid(b + w.z) with w_j <= 0 for every distance input j.

    y: 1 = genuine, 0 = attack.
    """
    xa = np.asarray(x, dtype=np.float64)
    ya = np.asarray(y, dtype=np.float64)
    n, d = xa.shape
    if len(feature_names) != d or len(distance_mask) != d:
        raise ValueError("feature_names and distance_mask must match the number of columns")
    if not set(np.unique(ya)) <= {0.0, 1.0}:
        raise ValueError("y must be 0 (attack) or 1 (genuine)")
    if c <= 0:
        raise ValueError("c must be positive")

    mean = xa.mean(axis=0)
    scale = xa.std(axis=0)
    scale[scale == 0] = 1.0
    z = (xa - mean) / scale

    def objective(params: FloatArray) -> tuple[float, FloatArray]:
        w, b = params[:d], params[d]
        m = z @ w + b
        # logloss_i = -(y log s(m) + (1 - y) log s(-m))
        loss = -(ya * log_expit(m) + (1.0 - ya) * log_expit(-m)).sum()
        residual = expit(m) - ya
        grad_w = c * (z.T @ residual) + w
        grad_b = c * residual.sum()
        return float(c * loss + 0.5 * w @ w), np.append(grad_w, grad_b)

    bounds = [(None, 0.0) if is_dist else (None, None) for is_dist in distance_mask]
    bounds.append((None, None))  # intercept
    result = minimize(
        objective,
        x0=np.zeros(d + 1),
        jac=True,
        method="L-BFGS-B",
        bounds=bounds,
        options={"maxiter": 10_000, "gtol": 1e-10, "ftol": 1e-14},
    )
    if not result.success:
        raise RuntimeError(f"fusion fit did not converge: {result.message}")

    coef = np.asarray(result.x[:d], dtype=np.float64)
    # L-BFGS-B keeps iterates inside the bounds; clip float noise at the boundary.
    coef[np.asarray(distance_mask)] = np.minimum(coef[np.asarray(distance_mask)], 0.0)
    model = FusionModel(
        feature_names=tuple(feature_names),
        distance_mask=tuple(bool(v) for v in distance_mask),
        mean=mean,
        scale=scale,
        coef=coef,
        intercept=float(result.x[d]),
    )
    assert_weight_signs(model)
    return model


def assert_weight_signs(model: FusionModel) -> None:
    """Guard run on every trained fusion artifact (SPEC 7.4)."""
    bad = [
        name
        for name, is_dist, w in zip(model.feature_names, model.distance_mask, model.coef)
        if is_dist and w > 0
    ]
    if bad:
        raise WeightSignError(f"distance inputs with positive weight: {bad}")
