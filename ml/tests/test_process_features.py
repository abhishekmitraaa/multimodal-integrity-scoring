"""Process features (SPEC 6.2) on hand-built SYNTHETIC event logs with known answers."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
import yaml

from integrity_ml.process_features import (
    FEATURES, ProcessConfig, baseline, pooled_within_sd, process_distance, process_features, vector,
)

CFG = ProcessConfig()


class Log:
    """A one-line editor: typed characters go at the cursor; Backspace deletes before it."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.t = 1.0
        self.doc = 0          # document length
        self.cursor = 0
        self.version = 0

    def _add(self, etype: str, data: dict[str, Any], t: float | None = None) -> None:
        self.events.append({"type": etype, "t_client_us": int(round((self.t if t is None else t) * 1e6)), "data": data})

    def _change(self, offset: int, del_len: int, text: str, cause: str = "typed", line: int = 1) -> None:
        self.version += 1
        self._add("content_change", {"version_id": self.version, "idx": 0, "n": 1, "offset": offset, "del_len": del_len,
                                     "ins_len": len(text), "text": text, "start_line": line, "start_col": offset + 1,
                                     "end_line": line, "end_col": offset + 1 + del_len, "cause": cause,
                                     "undo": False, "redo": False, "flush": False}, self.t + 0.01)
        self.doc += len(text) - del_len

    def key(self, gap: float = 0.15, hold: float = 0.08, char: str = "a", line: int = 1) -> "Log":
        self.t += gap
        self._add("keydown", {"code": "KeyA", "cat": "letter", "rep": False, "mods": 0, "target": "editor"})
        self._change(self.cursor, 0, char, line=line)
        self.cursor += 1
        self._add("keyup", {"code": "KeyA", "cat": "letter", "target": "editor"}, self.t + hold)
        return self

    def keys(self, n: int, gap: float = 0.15, hold: float = 0.08, line: int = 1) -> "Log":
        for _ in range(n):
            self.key(gap, hold, line=line)
        return self

    def backspace(self, gap: float = 0.15) -> "Log":
        self.t += gap
        self._add("keydown", {"code": "Backspace", "cat": "backspace", "rep": False, "mods": 0, "target": "editor"})
        self._change(self.cursor - 1, 1, "")
        self.cursor -= 1
        self._add("keyup", {"code": "Backspace", "cat": "backspace", "target": "editor"}, self.t + 0.08)
        return self

    def run(self) -> "Log":
        self.t += 0.5
        self._add("run", {"kind": "test", "n_tests": 3, "n_passed": 3, "status": "ok", "dur_ms": 10, "version_id": self.version})
        return self


def test_feature_list_matches_spec_and_config_loads() -> None:
    assert len(FEATURES) == 14
    from integrity_ml import process_features as pf
    import pathlib
    cfg = yaml.safe_load((pathlib.Path(pf.__file__).parents[3] / "config" / "features.yaml").read_text(encoding="utf-8"))
    assert ProcessConfig.from_config(cfg["process"]) == CFG


def test_steady_linear_typist() -> None:
    f = process_features(Log().keys(100).events, CFG)
    assert f["linearity"] == 1.0 and f["short_survival"] == 0.0 and f["revision_rate"] == 0.0
    assert f["ins_del_ratio"] == 100.0 and f["edit_locality"] == 0.0
    assert f["pause_frac_200ms"] == 0.0 and f["pause_frac_2s"] == 0.0 and f["burst_len"] == 100.0
    assert f["flight_cv"] == pytest.approx(0.0, abs=1e-6) and f["hold_cv"] == pytest.approx(0.0, abs=1e-6)
    assert f["pre_burst_pause"] is None                                # one burst: no pause before any burst


def test_bursts_and_the_pause_before_them() -> None:
    log = Log().keys(50)
    log.keys(1, gap=5.0)                                               # a 5 s pause, then the second burst
    log.keys(49)
    f = process_features(log.events, CFG)
    assert f["burst_len"] == 50.0
    assert f["pause_frac_2s"] == pytest.approx(1 / 99)
    assert f["pre_burst_pause"] == pytest.approx(5.0 / 0.15)          # pause / median intra-burst interval


def test_corrections_survival_and_revision_rate() -> None:
    log = Log().keys(40)
    for _ in range(10):
        log.backspace()
    log.keys(10)
    f = process_features(log.events, CFG)
    assert f["revision_rate"] == pytest.approx(100 * 10 / 50)
    assert f["short_survival"] == pytest.approx(10 / 50)              # 10 of 50 typed characters were deleted
    assert f["ins_del_ratio"] == pytest.approx(50 / 11)
    assert f["linearity"] == 1.0                                       # typing at the end, corrections included


def test_non_linear_insertion_and_edit_locality() -> None:
    log = Log().keys(30)
    for i in range(30):                                                # then insert at the very start each time
        log.cursor = 0
        log.key(line=1 + (i % 2) * 4)
    f = process_features(log.events, CFG)
    assert f["linearity"] == pytest.approx(29 / 59)                    # 29 at the end (the first has no frontier), 30 at the front
    assert f["edit_locality"] == 0.0                                   # median |line jump|: mostly same line in this log
    jumpy = Log()
    for i in range(40):
        jumpy.key(line=1 + (i % 2) * 10)
    assert process_features(jumpy.events, CFG)["edit_locality"] == 10.0


def test_runs_and_edits_between_them() -> None:
    log = Log().keys(20).run().keys(30).run().keys(10).run()
    f = process_features(log.events, CFG)
    assert f["runs_per_100"] == pytest.approx(100 * 3 / 60)
    assert f["edits_between_runs"] == pytest.approx(20.0)              # median of 30 and 10


def test_speed_cv_over_active_bins() -> None:
    log = Log()
    for burst, n in enumerate((10, 20, 30)):                           # three 10 s bins with 10, 20, 30 chars
        log.t = 1.0 + burst * 10
        log.keys(n, gap=0.1)
    f = process_features(log.events, CFG)
    x = np.array([10.0, 20.0, 30.0])
    assert f["speed_cv"] == pytest.approx(x.std() / x.mean())


def test_window_counts_only_inside_but_tracks_state_from_before() -> None:
    log = Log().keys(60)
    t_mid = log.t
    for _ in range(5):
        log.backspace()                                                # deletes characters typed before the window
    log.keys(40)
    f = process_features(log.events, CFG, window=(t_mid + 0.01, log.t + 1))
    assert f["revision_rate"] == pytest.approx(100 * 5 / 40)
    assert f["short_survival"] == 0.0                                  # the deleted ones were typed outside the window
    assert f["pause_frac_200ms"] is None                               # 45 keydowns < min_keydowns


def test_thin_input_is_unavailable_and_tracking_is_bounded() -> None:
    f = process_features(Log().keys(10).events, CFG)
    assert all(v is None for k, v in f.items() if k not in ("edit_locality", "speed_cv"))
    capped = process_features(Log().keys(100).events, ProcessConfig(max_changes=50))
    assert capped["linearity"] is None and capped["short_survival"] is None      # said, not guessed
    assert capped["revision_rate"] == 0.0                                        # other features still computed


def test_snapshot_resynchronises_after_a_lost_change() -> None:
    log = Log().keys(40)
    log._add("snapshot", {"text": "x" * 45, "len": 45, "reason": "resync"})
    log.doc = log.cursor = 45
    log.keys(40)
    f = process_features(log.events, CFG)
    assert f["linearity"] == 1.0                                       # the first char after a resync has no frontier: not counted


def test_baseline_pooled_sd_and_distance() -> None:
    n = len(FEATURES)
    a1, a2 = np.full(n, 1.0), np.full(n, 3.0)                          # user A: mean 2, deviations ±1
    b1, b2 = np.full(n, 10.0), np.full(n, 10.0)                        # user B: no spread
    s = pooled_within_sd({"A": [a1, a2], "B": [b1, b2]})
    assert s == pytest.approx(np.full(n, np.sqrt(2 / 2)))             # (1 + 1 + 0 + 0) / (1 + 1)
    b = baseline([a1, np.where(np.arange(n) == 0, np.nan, a2)])
    assert b[0] == 1.0 and b[1] == 2.0                                 # unavailable values ignored
    x = np.full(n, 4.0)
    assert process_distance(x, np.full(n, 2.0), np.full(n, 2.0)) == pytest.approx(1.0)
    assert process_distance(np.full(n, np.nan), b, s) is None
    v = vector(process_features(Log().keys(100).events, CFG))
    assert v.shape == (n,) and np.isnan(v[FEATURES.index("pre_burst_pause")])
