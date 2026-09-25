"""Keystroke pairing and latencies (SPEC 6.1) on hand-built SYNTHETIC sequences."""

from __future__ import annotations

import numpy as np

from integrity_ml.keystroke import KeyEvent, Keystroke, latencies, pair_keystrokes


def down(code: str, t_ms: float, rep: bool = False) -> KeyEvent:
    return KeyEvent("keydown", code, round(t_ms * 1000), rep)


def up(code: str, t_ms: float) -> KeyEvent:
    return KeyEvent("keyup", code, round(t_ms * 1000))


def test_sequential_keys() -> None:
    ks, stats = pair_keystrokes([down("KeyA", 0), up("KeyA", 80), down("KeyB", 150), up("KeyB", 220)])
    assert ks == [Keystroke("KeyA", 0, 80_000), Keystroke("KeyB", 150_000, 220_000)]
    lat = latencies(ks)
    assert lat.hl_ms.tolist() == [80.0, 70.0]
    assert lat.pl_ms.tolist() == [150.0]
    assert lat.il_ms.tolist() == [70.0]
    assert lat.rl_ms.tolist() == [140.0]
    assert stats.unmatched_keydowns == stats.unmatched_keyups == stats.repeats == 0


def test_rollover_gives_negative_il() -> None:
    ks, _ = pair_keystrokes([down("KeyA", 0), down("KeyB", 50), up("KeyA", 80), up("KeyB", 120)])
    lat = latencies(ks)
    assert lat.hl_ms.tolist() == [80.0, 70.0]
    assert lat.il_ms.tolist() == [-30.0]
    assert lat.rl_ms.tolist() == [40.0]


def test_nested_press_orders_by_press_time() -> None:
    # Shift held around a letter: B is released first, so IL and RL are both negative.
    ks, _ = pair_keystrokes([down("ShiftLeft", 0), down("KeyB", 10), up("KeyB", 20), up("ShiftLeft", 30)])
    assert [k.code for k in ks] == ["ShiftLeft", "KeyB"]
    lat = latencies(ks)
    assert lat.il_ms.tolist() == [-20.0]
    assert lat.rl_ms.tolist() == [-10.0]


def test_auto_repeat_is_excluded_and_counted() -> None:
    events = [down("KeyA", 0), down("KeyA", 500, rep=True), down("KeyA", 533, rep=True), up("KeyA", 600)]
    ks, stats = pair_keystrokes(events)
    assert ks == [Keystroke("KeyA", 0, 600_000)]
    assert stats.repeats == 2


def test_keyup_matches_most_recent_unmatched_keydown() -> None:
    # A lost keyup: the second keydown of the same code is the one that gets matched.
    ks, stats = pair_keystrokes([down("KeyA", 0), down("KeyA", 100), up("KeyA", 150)])
    assert ks == [Keystroke("KeyA", 100_000, 150_000)]
    assert stats.unmatched_keydowns == 1


def test_unmatched_events_are_dropped_and_counted() -> None:
    ks, stats = pair_keystrokes([up("KeyZ", 0), down("KeyA", 10), up("KeyA", 60), down("KeyB", 90)])
    assert [k.code for k in ks] == ["KeyA"]
    assert (stats.unmatched_keyups, stats.unmatched_keydowns, stats.keystrokes) == (1, 1, 1)


def test_empty_and_single() -> None:
    lat = latencies([])
    assert lat.hl_ms.shape == (0,) and lat.pl_ms.shape == (0,)
    one = latencies([Keystroke("KeyA", 0, 90_000)])
    assert one.hl_ms.tolist() == [90.0]
    assert one.il_ms.shape == (0,)
    assert np.all(np.isfinite(one.hl_ms))
