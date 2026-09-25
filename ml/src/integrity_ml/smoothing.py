"""EWMA smoothing of the integrity score and its effect on time-to-detection (SPEC 8.3).

Smoothing runs on the logit:  l~_k = lam * logit(S_k) + (1 - lam) * l~_{k-1},  l~_0 = logit(S_0).
lam = 1 means no smoothing.
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.special import expit, logit

FloatArray = NDArray[np.float64]


def ewma_logit(scores: ArrayLike, lam: float) -> FloatArray:
    """Smoothed scores S~_k for a sequence of raw tick scores S_k in (0, 1)."""
    if not 0.0 < lam <= 1.0:
        raise ValueError("lam must be in (0, 1]")
    raw = logit(np.clip(np.asarray(scores, dtype=np.float64), 1e-12, 1 - 1e-12))
    out = np.empty_like(raw)
    state = 0.0
    for k, value in enumerate(raw):
        state = value if k == 0 else lam * value + (1.0 - lam) * state
        out[k] = state
    return np.asarray(expit(out), dtype=np.float64)


def ticks_to_cross(l0: float, l1: float, theta: float, lam: float) -> int | None:
    """Post-onset ticks until the smoothed logit drops below theta.

    Model: the smoothed logit is l0 when the attack starts, then every raw tick has logit l1.
    Returns 0 if already below theta, None if l1 >= theta (never crosses).

    Closed form (0 < lam < 1): after k ticks l~_k = l1 + (1 - lam)^k (l0 - l1), so the first
    crossing is k* = floor(ln r / ln(1 - lam)) + 1 with r = (theta - l1) / (l0 - l1).
    """
    if not 0.0 < lam <= 1.0:
        raise ValueError("lam must be in (0, 1]")
    if l0 < theta:
        return 0
    if l1 >= theta:
        return None
    if lam == 1.0:
        return 1
    r = (theta - l1) / (l0 - l1)
    return math.floor(math.log(r) / math.log(1.0 - lam)) + 1


def isolated_dip_threshold(l0: float, theta: float, lam: float) -> float:
    """A single-tick dip crosses theta only if its logit is below this value.

    From lam * l1 + (1 - lam) * l0 < theta. With lam = 0.5 a lone dip must go twice as far
    below theta as l0 sits above it, which is how smoothing suppresses one-window noise.
    """
    if not 0.0 < lam <= 1.0:
        raise ValueError("lam must be in (0, 1]")
    return (theta - (1.0 - lam) * l0) / lam
