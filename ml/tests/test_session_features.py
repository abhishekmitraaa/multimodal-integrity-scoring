"""Session signals on hand-built SYNTHETIC event logs (stored-event shape)."""

from __future__ import annotations

import hashlib
from typing import Any

import numpy as np
import pytest

from integrity_ml.session_features import (
    editor_keystrokes, enrollment_windows, exam_windows, habits, insertions, session_signals,
)

CLIP = 1.5


class Log:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.t = 1_000_000

    def add(self, etype: str, data: dict[str, Any], t: int | None = None) -> None:
        self.events.append({"type": etype, "t_client_us": self.t if t is None else t, "data": data})

    def key(self, code: str, cat: str = "letter", gap_ms: float = 150, hold_ms: float = 80, mods: int = 0, text: str | None = "a") -> None:
        self.t += int(gap_ms * 1000)
        base = {"code": code, "cat": cat, "rep": False, "mods": mods, "target": "editor"}
        self.add("keydown", base)
        if text is not None:
            self.add("content_change", {"ins_len": len(text), "text": text, "cause": "typed", "flush": False}, self.t + 300)
        self.add("keyup", base, self.t + int(hold_ms * 1000))

    def change(self, text: str, cause: str, dt_ms: float = 500) -> None:
        self.t += int(dt_ms * 1000)
        self.add("content_change", {"ins_len": len(text), "text": text, "cause": cause, "flush": False})


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def typing(n: int, gap_ms: float = 150) -> Log:
    log = Log()
    for i in range(n):
        log.key("KeyA" if i % 2 else "KeyB", gap_ms=gap_ms)
    return log


def test_windows_enrollment_and_exam() -> None:
    ks = editor_keystrokes(typing(150).events)
    assert len(ks) == 150
    enroll = enrollment_windows(ks, 70, CLIP)
    assert len(enroll) == 2 and enroll[0].shape == (70, 5)
    exam = exam_windows(ks, 70, 35, CLIP)
    assert len(exam) == 3                       # starts at 0, 35, 70
    assert exam[0][1] == pytest.approx(ks[69].down_us / 1e6)


def test_long_pauses_are_clipped_in_windows() -> None:
    log = typing(40)
    log.key("KeyC", gap_ms=10_000)              # a 10 s thinking pause
    for _ in range(40):
        log.key("KeyA")
    [w] = enrollment_windows(editor_keystrokes(log.events), 70, CLIP)
    assert w[:, 3].max() == pytest.approx(CLIP)      # PL column


def test_keys_in_the_find_widget_and_repeats_are_ignored() -> None:
    log = typing(5)
    log.add("keydown", {"code": "KeyF", "cat": "letter", "rep": False, "target": "find_widget"})
    log.add("keyup", {"code": "KeyF", "cat": "letter", "rep": False, "target": "find_widget"})
    assert len(editor_keystrokes(log.events)) == 5


def test_habits_constant_rhythm_and_revisions() -> None:
    log = typing(200, gap_ms=120)
    for _ in range(20):
        log.key("Backspace", cat="backspace", gap_ms=120, text=None)
    h = habits(log.events)
    assert h.keystrokes == 220 and h.typed_chars == 200
    assert h.interval_cv is not None and h.interval_cv < 0.01
    assert h.revisions_per_100 == pytest.approx(10.0)
    assert h.pause_share_2s == 0.0
    assert h.chars_per_minute == pytest.approx(200 / (219 * 0.12 / 60))   # typed chars per active minute


def test_external_paste_after_leaving_the_window() -> None:
    log = typing(10)
    log.change("", "typed")
    log.add("blur", {"target": "window"})
    log.t += 30_000_000
    log.add("focus", {"target": "window"})
    body = "def f(x):\n    return x * 2\n" * 3
    log.t += 2_000_000
    log.add("paste", {"len": len(body)})
    log.add("content_change", {"ins_len": len(body), "text": body, "cause": "paste", "flush": False})
    ins = insertions(log.events, large_insert_chars=32, coupling_s=10)
    assert ins.external_paste_chars == len(body)
    assert ins.away_seconds == pytest.approx(30.0)
    assert len(ins.away_then_external_paste) == 1
    assert ins.untyped_by_cause == {"paste": len(body)}
    assert ins.unexplained_large_inserts == []            # a real paste event backs it


def test_internal_paste_matches_an_earlier_cut() -> None:
    log = typing(10)
    moved = "    count = 1\n"
    log.add("cut", {"source": "editor", "len": len(moved), "sha256": sha(moved)})
    log.change(moved, "paste")
    ins = insertions(log.events, 32, 10)
    assert [p.provenance for p in ins.pastes] == ["internal"] and ins.external_paste_chars == 0


def test_reconciliation_flags_text_without_keystrokes() -> None:
    log = typing(10)
    injected = "x" * 50
    log.change(injected, "typed")                 # a client claiming "typed" with no keydowns
    ins = insertions(log.events, 32, 10)
    assert ins.unexplained_large_inserts == [(pytest.approx(log.t / 1e6), 50, "typed")]
    assert ins.typed_chars_beyond_keystrokes == 50


def test_session_signals_bundle() -> None:
    s = session_signals(typing(80).events, 32, 10)
    assert len(s.keystrokes) == 80 and s.habits is not None and s.insertions is not None
    assert s.duration_s > 10
