"""Real-keyboard check report on hand-built SYNTHETIC runs (docs/keycheck.md)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from integrity_eval.keycheck import (
    KeycheckError, hold_stats, jank_stats, load_config, load_runs, main, overlap_stats, render,
    timestamp_grid_us,
)

CFG = load_config()


def ev(task: str, type_: str, code: str, ts: float, now: float | None = None, rep: bool = False) -> dict[str, Any]:
    return {"task": task, "type": type_, "code": code, "rep": rep, "mods": 0, "trusted": True,
            "composing": False, "ts": ts, "now": ts + 0.5 if now is None else now}


def make_run(events: list[dict[str, Any]], blocks: list[list[float]] | None = None, synthetic: bool = True) -> dict[str, Any]:
    return {
        "format": "keycheck.v1", "dataset": "development", "not_for_study": True, "synthetic": synthetic,
        "created_at": "2026-09-26T00:00:00Z", "tester": "SYN-TEST0001", "keyboard_type": "external",
        "keyboard_label": "", "os": "windows", "layout": "qwerty",
        "browser": {"brand": "chrome", "version": "140.0.0.0"}, "cross_origin_isolated": True,
        "timer_resolution_us": 5, "protocol": {"jank_block_ms": 80, "jank_period_ms": 250},
        "tasks": [], "jank_blocks": blocks or [], "events": events, "_file": "synthetic.dev.json",
    }


def test_overlaps_with_and_without_modifiers() -> None:
    events = [
        ev("prose", "keydown", "KeyA", 0), ev("prose", "keydown", "KeyB", 50),
        ev("prose", "keyup", "KeyA", 80), ev("prose", "keyup", "KeyB", 120),
        ev("prose", "keydown", "KeyC", 200), ev("prose", "keyup", "KeyC", 260),
        ev("prose", "keydown", "ShiftLeft", 300), ev("prose", "keydown", "KeyD", 310),
        ev("prose", "keyup", "KeyD", 330), ev("prose", "keyup", "ShiftLeft", 340),
    ]
    o = overlap_stats(make_run(events), ["prose"], top=5)
    assert (o.keystrokes, o.pairs) == (5, 4)          # IL: -30, 80, 40, -30
    assert o.overlap_frac == pytest.approx(0.5)
    assert o.pairs_without_modifiers == 2               # A→B and B→C
    assert o.overlap_frac_without_modifiers == pytest.approx(0.5)
    assert o.median_negative_il_ms == pytest.approx(-30.0)
    assert dict(o.top_pairs) == {"KeyA→KeyB": 1, "ShiftLeft→KeyD": 1}


def test_keys_never_pair_across_tasks() -> None:
    o = overlap_stats(make_run([ev("prose", "keydown", "KeyA", 0), ev("code", "keyup", "KeyA", 50)]), ["prose", "code"], 5)
    assert (o.keystrokes, o.unmatched) == (0, 2)


def test_hold_with_flagged_repeats() -> None:
    events = [ev("hold", "keydown", "KeyA", 0)]
    events += [ev("hold", "keydown", "KeyA", t, rep=True) for t in (500, 533, 566)]
    events += [ev("hold", "keyup", "KeyA", 600)]
    [hs] = hold_stats(make_run(events))
    assert (hs.holds, hs.repeats, hs.missing_repeat_flag, hs.keyups_during_hold) == (1, 3, 0, 0)
    assert hs.initial_delay_ms == pytest.approx(500)
    assert hs.repeat_interval_ms == pytest.approx(33)


def test_hold_with_a_keyup_per_repeat() -> None:
    events = [
        ev("hold", "keydown", "KeyA", 0), ev("hold", "keyup", "KeyA", 500),
        ev("hold", "keydown", "KeyA", 500.1, rep=True), ev("hold", "keyup", "KeyA", 533),
        ev("hold", "keydown", "KeyA", 533.1, rep=True), ev("hold", "keyup", "KeyA", 600),
    ]
    [hs] = hold_stats(make_run(events))
    assert (hs.holds, hs.repeats, hs.keyups_during_hold) == (1, 2, 2)


def test_hold_repeat_without_flag_and_separate_holds() -> None:
    events = [
        ev("hold", "keydown", "Backspace", 0), ev("hold", "keydown", "Backspace", 500),
        ev("hold", "keyup", "Backspace", 600),
        ev("hold", "keydown", "Backspace", 2000), ev("hold", "keyup", "Backspace", 2100),
    ]
    [hs] = hold_stats(make_run(events))
    assert (hs.holds, hs.repeats, hs.missing_repeat_flag) == (2, 1, 1)


def _blocks(n: int) -> list[list[float]]:
    return [[100.0 + 250 * k, 180.0 + 250 * k] for k in range(n)]


def test_jank_input_time_verdict() -> None:
    # Keys pressed mid-block carry a timeStamp inside it and are handled when the block ends.
    inside = [ev("jank", "keydown", "KeyA", 140 + 250 * k, now=180.2 + 250 * k) for k in range(10)]
    outside = [ev("jank", "keydown", "KeyB", 210 + 250 * k + d, now=210.3 + 250 * k + d) for k in range(10) for d in (0, 20)]
    j = jank_stats(make_run(inside + outside, _blocks(10)), CFG)
    assert j.keydowns == 30
    assert j.inside_frac == pytest.approx(1 / 3)
    assert j.verdict.startswith("input time")


def test_jank_dispatch_time_verdict() -> None:
    # The same presses stamped at dispatch: just after each block, with no lag.
    queued = [ev("jank", "keydown", "KeyA", 180.1 + 250 * k, now=180.2 + 250 * k) for k in range(10)]
    outside = [ev("jank", "keydown", "KeyB", 210 + 250 * k + d, now=210.3 + 250 * k + d) for k in range(10) for d in (0, 20)]
    j = jank_stats(make_run(queued + outside, _blocks(10)), CFG)
    assert j.inside_frac == 0
    assert j.verdict.startswith("dispatch time")


def test_jank_needs_enough_key_presses() -> None:
    j = jank_stats(make_run([ev("jank", "keydown", "KeyA", 140, now=180)], _blocks(1)), CFG)
    assert j.verdict == "not enough key presses in task 4"


def test_timestamp_grid() -> None:
    assert timestamp_grid_us([1.1, 2.2, 1234.5]) == 100
    assert timestamp_grid_us([1.0, 2.0, 7.0]) == 1_000
    assert timestamp_grid_us([0.005, 0.010, 1234.565]) == 5
    assert timestamp_grid_us([0.0013]) == 0


def _write(folder: Path, name: str, run: dict[str, Any]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(json.dumps({k: v for k, v in run.items() if k != "_file"}), encoding="utf-8")


def test_load_runs_refuses_non_development_and_mixed_files(tmp_path: Path) -> None:
    bad = make_run([])
    bad["dataset"] = "study"
    _write(tmp_path / "a", "x.dev.json", bad)
    with pytest.raises(KeycheckError, match="development"):
        load_runs(tmp_path / "a")
    _write(tmp_path / "b", "x.dev.json", make_run([], synthetic=True))
    _write(tmp_path / "b", "y.dev.json", make_run([], synthetic=False))
    with pytest.raises(KeycheckError, match="mix"):
        load_runs(tmp_path / "b")
    with pytest.raises(KeycheckError, match="no \\*.dev.json"):
        load_runs(tmp_path / "empty")


def test_load_runs_refuses_a_folder_inside_the_repository(tmp_path: Path) -> None:
    _write(tmp_path / "data", "x.dev.json", make_run([]))
    with pytest.raises(KeycheckError, match="inside the repository"):
        load_runs(tmp_path / "data", repo_root=tmp_path)


def test_render_and_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    events = [ev("prose", "keydown", "KeyA", 0), ev("prose", "keyup", "KeyA", 80),
              ev("hold", "keydown", "KeyA", 1000), ev("hold", "keydown", "KeyA", 1500, rep=True),
              ev("hold", "keyup", "KeyA", 1600)]
    report = render([make_run(events)], CFG)
    assert "DEVELOPMENT DATA" in report and "SYNTHETIC" in report
    assert "not enough key presses in task 4" in report
    _write(tmp_path, "run.dev.json", make_run(events))
    assert main([str(tmp_path)]) == 0
    assert "# Real-keyboard check report" in capsys.readouterr().out
    assert main([str(tmp_path / "missing")]) == 2
    out = tmp_path / "report.md"
    assert main([str(tmp_path), "--out", str(out)]) == 0
    assert "µs" in out.read_text(encoding="utf-8")
    assert main([str(tmp_path), "--out", str(Path(__file__).resolve().parent / "report.md")]) == 2
