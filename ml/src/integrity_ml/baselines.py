"""Non-deep keystroke identity baselines (SPEC 7.2, D-031). Both return a distance (low = genuine).

1. Digraph (SPEC 7.2). The gallery profile keeps ordered key pairs seen at least `min_occurrences`
   times, with their median PL, and keys seen at least that often, with their median HL. The
   distance to a query is the mean absolute difference over every shared item (digraphs and keys
   together: Manhattan divided by the number of shared items). It is unavailable (None) when
   fewer than `min_shared_items` items are shared.
2. Sequence statistics (always available). Each sequence becomes 8 numbers: mean and SD of HL,
   PL, IL and RL in ms. The distance is the mean over the 8 of |query - gallery mean| / scale,
   where scale is the pooled within-subject mean absolute deviation on training subjects.

Both pool the whole gallery into one model: one ~70-keystroke sentence is too sparse for a
digraph profile, so TypeNet's per-sample averaging (Eq. 5) does not apply to them.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from numpy.typing import NDArray

from .keystroke import Keystroke, latencies

FloatArray = NDArray[np.float64]
KeySeq = Sequence[Keystroke]


# ---------------------------------------------------------------- digraph (SPEC 7.2)

@dataclass(frozen=True)
class DigraphProfile:
    digraph_pl_ms: dict[tuple[str, str], float]
    key_hl_ms: dict[str, float]


def digraph_profile(sequences: Sequence[KeySeq], min_occurrences: int) -> DigraphProfile:
    pl: dict[tuple[str, str], list[float]] = defaultdict(list)
    hl: dict[str, list[float]] = defaultdict(list)
    for seq in sequences:
        ks = sorted(seq, key=lambda k: (k.down_us, k.up_us))
        lat = latencies(ks)
        for i, k in enumerate(ks):
            hl[k.code].append(float(lat.hl_ms[i]))
            if i + 1 < len(ks):
                pl[(k.code, ks[i + 1].code)].append(float(lat.pl_ms[i]))
    return DigraphProfile(
        {pair: float(np.median(v)) for pair, v in pl.items() if len(v) >= min_occurrences},
        {code: float(np.median(v)) for code, v in hl.items() if len(v) >= min_occurrences},
    )


def digraph_distance(gallery: DigraphProfile, query: DigraphProfile, min_shared_items: int) -> float | None:
    diffs = [abs(gallery.digraph_pl_ms[p] - query.digraph_pl_ms[p]) for p in gallery.digraph_pl_ms.keys() & query.digraph_pl_ms.keys()]
    diffs += [abs(gallery.key_hl_ms[c] - query.key_hl_ms[c]) for c in gallery.key_hl_ms.keys() & query.key_hl_ms.keys()]
    if len(diffs) < min_shared_items:
        return None
    return float(np.mean(diffs))


# ---------------------------------------------------------------- sequence statistics

def sequence_stats(seq: KeySeq) -> FloatArray:
    """[HL mean, HL sd, PL mean, PL sd, IL mean, IL sd, RL mean, RL sd] in ms (NaN if undefined)."""
    lat = latencies(sorted(seq, key=lambda k: (k.down_us, k.up_us)))
    out = []
    for values in (lat.hl_ms, lat.pl_ms, lat.il_ms, lat.rl_ms):
        out += [float(values.mean()), float(values.std())] if values.size else [float("nan")] * 2
    return np.array(out, dtype=np.float64)


def pooled_within_subject_mad(train_subjects: Sequence[Sequence[FloatArray]]) -> FloatArray:
    """Mean absolute deviation of each statistic around its own subject's mean, pooled."""
    deviations = [np.abs(np.vstack(stats) - np.nanmean(np.vstack(stats), axis=0))
                  for stats in train_subjects if len(stats) >= 2]
    if not deviations:
        raise ValueError("need training subjects with at least two sequences each")
    scale = np.nanmean(np.vstack(deviations), axis=0)
    if np.any(~np.isfinite(scale)) or np.any(scale <= 0):
        raise ValueError("degenerate scale: a statistic has no within-subject spread")
    return np.asarray(scale, dtype=np.float64)


def seqstat_distance(gallery_stats: Sequence[FloatArray], query_stats: FloatArray, scale: FloatArray) -> float:
    centre = np.nanmean(np.vstack(gallery_stats), axis=0)
    return float(np.nanmean(np.abs(query_stats - centre) / scale))
