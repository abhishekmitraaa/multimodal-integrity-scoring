"""Equal error rate for distance scores (low distance = genuine).

`eer_sweep` reproduces the TypeNet authors' published `eer_compute` (BiDAlab/TypeNet README): an
even grid of thresholds from min - step to max + step with step = (max - min) / steps, where the EER
is (FAR + FRR) / 2 at the first threshold where |FAR - FRR| is smallest. The README computes
1 - FAR and 1 - FRR and returns 100 minus their mean; that is algebraically the same thing.

`eer_exact` uses every distinct score as a candidate threshold. It is used for the global
(single-threshold) EER on our own data, which is how tau is used (SPEC 8.5).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray

FloatArray = NDArray[np.float64]


def _rates(genuine: FloatArray, impostor: FloatArray, thresholds: FloatArray) -> tuple[FloatArray, FloatArray]:
    """Accept when distance < threshold. FAR: impostors accepted. FRR: genuines rejected."""
    far = np.searchsorted(np.sort(impostor), thresholds, side="left") / impostor.size
    frr = 1.0 - np.searchsorted(np.sort(genuine), thresholds, side="left") / genuine.size
    return far, frr


def _at_min_gap(far: FloatArray, frr: FloatArray) -> float:
    i = int(np.argmin(np.abs(far - frr)))   # first index, as in the authors' code
    return float((far[i] + frr[i]) / 2.0)


def _check(genuine: ArrayLike, impostor: ArrayLike) -> tuple[FloatArray, FloatArray]:
    g = np.asarray(genuine, dtype=np.float64).ravel()
    imp = np.asarray(impostor, dtype=np.float64).ravel()
    if g.size == 0 or imp.size == 0:
        raise ValueError("need at least one genuine and one impostor score")
    if not (np.all(np.isfinite(g)) and np.all(np.isfinite(imp))):
        raise ValueError("scores must be finite")
    return g, imp


def eer_sweep(genuine: ArrayLike, impostor: ArrayLike, steps: int = 10_000) -> float:
    """EER in [0, 1] by the TypeNet authors' threshold sweep."""
    g, imp = _check(genuine, impostor)
    lo, hi = float(min(g.min(), imp.min())), float(max(g.max(), imp.max()))
    if hi == lo:
        return 0.5   # every score identical: no threshold separates anything
    step = (hi - lo) / steps
    thresholds = lo - step + step * np.arange(steps + 2)
    return _at_min_gap(*_rates(g, imp, thresholds))


def eer_exact(genuine: ArrayLike, impostor: ArrayLike) -> float:
    """EER in [0, 1] with every distinct score (and one value above the maximum) as a threshold."""
    g, imp = _check(genuine, impostor)
    scores = np.unique(np.concatenate([g, imp]))
    thresholds = np.append(scores, np.nextafter(scores[-1], np.inf))
    return _at_min_gap(*_rates(g, imp, thresholds))


@dataclass(frozen=True)
class EerSummary:
    mean: float
    sd: float
    n_subjects: int


def summarise(per_subject: Sequence[float]) -> EerSummary:
    values = np.asarray(per_subject, dtype=np.float64)
    if values.size == 0:
        return EerSummary(float("nan"), float("nan"), 0)
    return EerSummary(float(values.mean()), float(values.std(ddof=0)), int(values.size))
