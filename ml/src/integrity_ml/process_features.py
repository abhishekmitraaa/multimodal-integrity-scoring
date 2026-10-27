"""Process features (SPEC 6.2): how the code was written, aimed at the copy-type gap.

One function, process_features(), computes all of SPEC 6.2 over a time window: the whole module
for the baseline, a trailing horizon (120 s) in the exam. Events before the window still update
the document state (survival, linearity), but only events inside it are counted.

Choices where SPEC 6.2 leaves room [PROPOSED, config/features.yaml → process]:
- "typed chars" in a burst are character keydowns (letter, digit, symbol, bracket, whitespace);
- flight_cv and hold_cv use intervals shorter than the burst gap (pauses are pause_frac's job);
- linearity counts typed chars that follow an earlier insertion (the first one has no frontier);
- survival and linearity track at most max_changes content changes and a document of at most
  max_doc_units UTF-16 units (bounded cost and memory on a forged log: offsets and lengths come
  from the client); beyond that they are reported unavailable, not guessed.

The distance to the baseline needs per-feature scales s_k, the pooled within-user SD from
training users (study data): pooled_within_sd() fits them, process_distance() uses them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
from numpy.typing import NDArray

from .keystroke import KeyEvent, pair_keystrokes

Event = Mapping[str, Any]
CHAR_CATS = frozenset({"letter", "digit", "symbol", "bracket", "whitespace"})
FEATURES = (
    "ins_del_ratio", "pause_frac_200ms", "pause_frac_2s", "pre_burst_pause", "burst_len", "revision_rate",
    "short_survival", "edit_locality", "linearity", "speed_cv", "flight_cv", "hold_cv", "runs_per_100",
    "edits_between_runs",
)


@dataclass(frozen=True)
class ProcessConfig:
    pause_short_s: float = 0.2
    pause_long_s: float = 2.0
    burst_gap_s: float = 2.0
    large_burst_min_chars: int = 40
    speed_bin_s: float = 10.0
    min_keydowns: int = 50
    min_typed_chars: int = 30
    max_changes: int = 50_000
    max_doc_units: int = 200_000

    @classmethod
    def from_config(cls, process: Mapping[str, Any]) -> "ProcessConfig":
        short_ms, long_ms = process["pause_thresholds_ms"]
        return cls(short_ms / 1000, long_ms / 1000, process["burst_gap_ms"] / 1000, int(process["large_burst_min_chars"]),
                   float(process["speed_bin_s"]), int(process["min_keydowns"]), int(process["min_typed_chars"]),
                   int(process["max_changes"]), int(process["max_doc_units"]))


def _utf16_units(text: str) -> int:
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def _cv(x: NDArray[np.float64], min_n: int = 2) -> float | None:
    if x.size < min_n or x.mean() <= 0:
        return None
    return float(x.std() / x.mean())


def _median(x: Sequence[float]) -> float | None:
    return float(np.median(x)) if len(x) else None


class _DocTooLarge(Exception):
    pass


class _Doc:
    """The document as one tag per UTF-16 unit: the time a typed unit was inserted, or None.

    Enough to tell, on a deletion, which typed characters are removed and when they were typed.
    Out-of-range changes (a lost event) resynchronise to an untracked document. Never larger than
    max_units: offsets and lengths come from the client and are not trusted (_DocTooLarge).
    """

    def __init__(self, max_units: int) -> None:
        self.tags: list[float | None] = []
        self.max_units = max_units

    def apply(self, offset: int, del_len: int, ins: int, typed_at: float | None) -> list[float | None]:
        if offset > self.max_units or ins > self.max_units or len(self.tags) - min(del_len, len(self.tags)) + ins > self.max_units:
            raise _DocTooLarge
        if offset + del_len > len(self.tags):
            removed: list[float | None] = []
            self.tags = self.tags[:offset] + [None] * max(0, offset - len(self.tags))
        else:
            removed = self.tags[offset:offset + del_len]
            del self.tags[offset:offset + del_len]
        self.tags[offset:offset] = [typed_at] * ins
        return removed

    def reset(self, length: int) -> None:
        if length > self.max_units:
            raise _DocTooLarge
        self.tags = [None] * length


def process_features(events: Sequence[Event], cfg: ProcessConfig,
                     window: tuple[float, float] | None = None) -> dict[str, float | None]:
    """All SPEC 6.2 features over [window[0], window[1]] seconds (client clock); the whole session if None.

    A feature is None when its input is too thin (fewer than min_keydowns keydowns in the window,
    fewer than min_typed_chars typed characters for rates, no qualifying burst, fewer than two runs).
    """
    ev = [e for e in events if e.get("t_client_us") is not None]
    lo, hi = window if window is not None else (-np.inf, np.inf)
    inside = lambda t: lo <= t <= hi  # noqa: E731

    downs: list[tuple[float, str]] = []           # (time, category) of editor, non-repeat, non-modifier keydowns
    keys: list[KeyEvent] = []
    typed = deleted = 0
    revisions = 0
    runs: list[float] = []
    typed_times: list[tuple[float, int]] = []     # (time, typed chars) per typed insertion
    lines: list[int] = []
    linear = linear_den = 0         # linearity over typed chars that follow an earlier insertion
    frontier: int | None = None
    typed_units = typed_then_deleted = 0
    doc = _Doc(cfg.max_doc_units)
    changes = 0
    tracked = True
    group: list[Mapping[str, Any]] = []

    def apply_group(t: float) -> None:
        nonlocal frontier, linear, linear_den, typed_units, typed_then_deleted, deleted, typed, changes, tracked
        for d in sorted(group, key=lambda c: int(c["offset"]), reverse=True):    # all refer to the pre-event document
            changes += 1
            if changes > cfg.max_changes:
                tracked = False
            off, dl, text, cause = int(d["offset"]), int(d["del_len"]), str(d["text"]), str(d["cause"])
            units = _utf16_units(text)
            if d.get("flush"):
                if tracked:
                    try:
                        doc.reset(units)
                    except _DocTooLarge:
                        tracked, doc.tags = False, []
                frontier = None
                continue
            is_typed = cause == "typed"
            if tracked:
                try:
                    removed = doc.apply(off, dl, units, t if is_typed and inside(t) else None)
                except _DocTooLarge:                  # forged or absurd sizes: stop tracking, never allocate
                    tracked, doc.tags, removed = False, [], []
                if inside(t):
                    typed_then_deleted += sum(1 for r in removed if r is not None)
            if inside(t):
                deleted += dl
                lines.append(int(d["start_line"]))
                if is_typed and units:
                    typed += int(d["ins_len"])
                    typed_units += units
                    typed_times.append((t, int(d["ins_len"])))
                    if frontier is not None:          # the first insertion (or the first after a resync) has no "previous end"
                        linear_den += int(d["ins_len"])
                        if off == frontier:
                            linear += int(d["ins_len"])
            if frontier is not None and dl and off < frontier:       # deleting before the frontier moves it back
                frontier -= min(dl, frontier - off)
            if units:
                frontier = off + units
        group.clear()

    for e in ev:
        t, d = e["t_client_us"] / 1e6, e["data"]
        if e["type"] == "content_change":
            group.append(d)
            if int(d["idx"]) == int(d["n"]) - 1:
                apply_group(t)
        elif e["type"] == "snapshot":
            if group:
                apply_group(t)
            n = _utf16_units(str(d.get("text", "")))                  # the text itself, not the client's "len"
            if tracked and n != len(doc.tags):                        # resynchronise (reload, lost event)
                try:
                    doc.reset(n)
                except _DocTooLarge:
                    tracked, doc.tags = False, []
                frontier = None
        elif e["type"] in ("keydown", "keyup") and d.get("target", "editor") == "editor":
            if inside(t):
                keys.append(KeyEvent(e["type"], str(d["code"]), int(e["t_client_us"]), bool(d.get("rep"))))
            if e["type"] == "keydown" and inside(t) and not d.get("rep") and d.get("cat") != "modifier":
                downs.append((t, str(d.get("cat", "other"))))
                if d.get("cat") == "backspace":
                    revisions += 1
        elif e["type"] == "run" and inside(t):
            runs.append(t)
    if group:
        apply_group(ev[-1]["t_client_us"] / 1e6)

    out: dict[str, float | None] = dict.fromkeys(FEATURES)
    enough_typed = typed >= cfg.min_typed_chars
    out["ins_del_ratio"] = typed / (deleted + 1) if enough_typed else None
    out["revision_rate"] = 100.0 * revisions / typed if enough_typed else None
    out["runs_per_100"] = 100.0 * len(runs) / typed if enough_typed else None
    out["edit_locality"] = _median(np.abs(np.diff(lines)).tolist()) if len(lines) >= 2 else None
    out["linearity"] = linear / linear_den if linear_den >= cfg.min_typed_chars and tracked else None
    out["short_survival"] = typed_then_deleted / typed_units if typed_units >= cfg.min_typed_chars and tracked else None
    if len(runs) >= 2:
        between = [sum(n for (tt, n) in typed_times if a < tt <= b) for a, b in zip(runs, runs[1:])]
        out["edits_between_runs"] = _median(between)

    if len(downs) >= cfg.min_keydowns:
        times = np.array([t for t, _ in downs])
        gaps = np.diff(times)
        out["pause_frac_200ms"] = float((gaps > cfg.pause_short_s).mean())
        out["pause_frac_2s"] = float((gaps > cfg.pause_long_s).mean())
        # bursts: runs of keydowns separated by pauses longer than the burst gap
        cuts = np.flatnonzero(gaps > cfg.burst_gap_s) + 1
        bursts = np.split(np.arange(len(downs)), cuts)
        out["burst_len"] = _median([len(b) for b in bursts])
        intra = gaps[gaps <= cfg.burst_gap_s]
        pre = [float(gaps[b[0] - 1]) for b in bursts[1:]
               if sum(1 for i in b if downs[i][1] in CHAR_CATS) >= cfg.large_burst_min_chars]
        if pre and intra.size and np.median(intra) > 0:
            out["pre_burst_pause"] = float(np.median(pre) / np.median(intra))
        ks = pair_keystrokes(keys)[0]
        flights = np.diff(np.array([k.down_us for k in ks], dtype=np.float64)) / 1e6
        out["flight_cv"] = _cv(flights[flights < cfg.burst_gap_s], min_n=20)
        holds = np.array([k.up_us - k.down_us for k in ks], dtype=np.float64) / 1e6
        out["hold_cv"] = _cv(holds[holds < cfg.burst_gap_s], min_n=20)

    if typed_times:
        start = typed_times[0][0] if not np.isfinite(lo) else lo
        bins: dict[int, int] = {}
        for tt, n in typed_times:
            bins[int((tt - start) // cfg.speed_bin_s)] = bins.get(int((tt - start) // cfg.speed_bin_s), 0) + n
        out["speed_cv"] = _cv(np.array(list(bins.values()), dtype=np.float64), min_n=3)
    return out


def vector(features: Mapping[str, float | None]) -> NDArray[np.float64]:
    """FEATURES order, NaN where unavailable."""
    return np.array([np.nan if features.get(k) is None else float(features[k]) for k in FEATURES], dtype=np.float64)  # type: ignore[arg-type]


def baseline(module_vectors: Sequence[NDArray[np.float64]]) -> NDArray[np.float64]:
    """b_u: the mean over the participant's practice modules, per feature, ignoring unavailable values."""
    stacked = np.stack(module_vectors)
    with np.errstate(invalid="ignore"):
        counts = np.sum(~np.isnan(stacked), axis=0)
        return np.where(counts > 0, np.nansum(stacked, axis=0) / np.maximum(counts, 1), np.nan)


def pooled_within_sd(by_user: Mapping[str, Sequence[NDArray[np.float64]]]) -> NDArray[np.float64]:
    """s_k: pooled within-user SD over training users (each user's modules around their own mean).

    sqrt(sum_u sum_m (x - mean_u)^2 / sum_u (n_u - 1)), per feature over available values;
    NaN where no user has two available values.
    """
    ss = np.zeros(len(FEATURES))
    dof = np.zeros(len(FEATURES))
    for vectors in by_user.values():
        x = np.stack(vectors)
        ok = ~np.isnan(x)
        n = ok.sum(axis=0)
        with np.errstate(invalid="ignore"):
            mean = np.where(n > 0, np.nansum(x, axis=0) / np.maximum(n, 1), 0.0)
        ss += np.nansum(np.where(ok, (x - mean) ** 2, 0.0), axis=0)
        dof += np.maximum(n - 1, 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(dof > 0, np.sqrt(ss / dof), np.nan)


def process_distance(x: NDArray[np.float64], b: NDArray[np.float64], s: NDArray[np.float64]) -> float | None:
    """d_proc = mean_k |x_k - b_k| / s_k over features available in both and with s_k > 0; None if none."""
    with np.errstate(invalid="ignore", divide="ignore"):
        z = np.abs(x - b) / s
    ok = np.isfinite(z) & (s > 0)
    return float(z[ok].mean()) if ok.any() else None
