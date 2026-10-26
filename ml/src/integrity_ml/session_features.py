"""Signals from one recorded session (the events as stored), for the baseline and the exam report.

This is the first P3 slice (D-036). One function per signal, shared by the backend report and
offline analysis (SPEC 6: the server never reimplements a feature).

- Keystrokes: editor keydown/keyup paired as in SPEC 6.1. TypeNet windows of M keystrokes:
  non-overlapping for enrollment, sliding for the exam.
- Typing habits (SPEC 6.2 subset): interval spread, pause shares, revisions, typing speed.
- Clipboard and insertion (SPEC 6.4): paste provenance, untyped insertion, time away from the
  window, focus-loss→paste coupling.
- Reconciliation (D-026, first version): large insertions without matching evidence, and typed
  characters that exceed the character-producing keystrokes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np
from numpy.typing import NDArray

from .keystroke import KeyEvent, Keystroke, pair_keystrokes
from .sequences import legacy_keycode, typenet_matrix

Event = Mapping[str, Any]            # {"type", "t_client_us", "data"}; server events may lack t_client_us
UNTYPED_CAUSES = frozenset({"paste", "drop", "find_replace", "other", "unknown"})
CHAR_CATS = frozenset({"letter", "digit", "symbol", "bracket", "whitespace"})


def _client(events: Sequence[Event]) -> list[Event]:
    return [e for e in events if e.get("t_client_us") is not None]


def _sha(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- keystrokes and windows

def editor_keystrokes(events: Sequence[Event]) -> list[Keystroke]:
    keys = [KeyEvent(e["type"], str(e["data"]["code"]), int(e["t_client_us"]), bool(e["data"].get("rep")))
            for e in _client(events)
            if e["type"] in ("keydown", "keyup") and e["data"].get("target", "editor") == "editor"]
    return pair_keystrokes(keys)[0]


def _window(ks: Sequence[Keystroke], m: int, clip_s: float) -> NDArray[np.float32]:
    x, _ = typenet_matrix(ks, m, keycode=legacy_keycode)
    x[:, 1:] = np.clip(x[:, 1:], -clip_s, clip_s)      # long thinking pauses (features.keystroke.latency_clip_ms)
    return x


def enrollment_windows(ks: Sequence[Keystroke], m: int, clip_s: float) -> list[NDArray[np.float32]]:
    """Non-overlapping windows of exactly m keystrokes (SPEC 6.1); a shorter remainder is dropped."""
    return [_window(ks[i:i + m], m, clip_s) for i in range(0, len(ks) - m + 1, m)]


def exam_windows(ks: Sequence[Keystroke], m: int, stride: int, clip_s: float) -> list[tuple[NDArray[np.float32], float]]:
    """Sliding windows (SPEC 6.1) with the time (s) of each window's last key press."""
    return [(_window(ks[i:i + m], m, clip_s), ks[i + m - 1].down_us / 1e6) for i in range(0, len(ks) - m + 1, stride)]


# ---------------------------------------------------------------- typing habits

@dataclass(frozen=True)
class Habits:
    keystrokes: int
    interval_cv: float | None          # coefficient of variation of key-to-key intervals (< 2 s)
    pause_share_2s: float | None       # share of key-to-key intervals longer than 2 s
    revisions_per_100: float | None    # Backspace/Delete per 100 typed characters
    typed_chars: int
    chars_per_minute: float | None     # typed characters per minute of active typing


def habits(events: Sequence[Event], pause_s: float = 2.0) -> Habits:
    ev = _client(events)
    downs = [e["t_client_us"] / 1e6 for e in ev if e["type"] == "keydown" and e["data"].get("target", "editor") == "editor"
             and e["data"].get("cat") != "modifier" and not e["data"].get("rep")]
    gaps = np.diff(downs) if len(downs) > 1 else np.array([])
    short = gaps[gaps < pause_s]
    typed = sum(int(e["data"]["ins_len"]) for e in ev if e["type"] == "content_change" and e["data"]["cause"] == "typed")
    revisions = sum(1 for e in ev if e["type"] == "keydown" and e["data"].get("cat") == "backspace" and not e["data"].get("rep"))
    active_min = float(short.sum()) / 60 if short.size else 0.0
    return Habits(
        keystrokes=len(downs),
        interval_cv=float(short.std() / short.mean()) if short.size >= 20 else None,
        pause_share_2s=float((gaps >= pause_s).mean()) if gaps.size >= 20 else None,
        revisions_per_100=100.0 * revisions / typed if typed >= 30 else None,
        typed_chars=typed,
        chars_per_minute=typed / active_min if active_min > 0.2 else None,
    )


# ---------------------------------------------------------------- clipboard, insertion, focus

@dataclass(frozen=True)
class Paste:
    t: float
    chars: int
    provenance: str            # internal | problem_statement | external


@dataclass(frozen=True)
class Insertions:
    typed_chars: int
    untyped_chars: int
    untyped_by_cause: dict[str, int]
    pastes: list[Paste]
    external_paste_chars: int
    away_seconds: float
    away_then_external_paste: list[float]        # times of external pastes soon after returning to the window
    unexplained_large_inserts: list[tuple[float, int, str]]   # (time, chars, client cause)
    typed_chars_beyond_keystrokes: int


def insertions(events: Sequence[Event], large_insert_chars: int, coupling_s: float) -> Insertions:
    ev = _client(events)
    copies: dict[str, str] = {}
    pastes: list[Paste] = []
    by_cause: dict[str, int] = {}
    typed = 0
    away, away_start, returns = 0.0, None, []
    unexplained: list[tuple[float, int, str]] = []
    char_keydowns = 0
    typed_nonspace = 0
    paste_events = [(e["t_client_us"] / 1e6, int(e["data"]["len"])) for e in ev if e["type"] == "paste"]
    chord_downs = [e["t_client_us"] / 1e6 for e in ev if e["type"] == "keydown" and (int(e["data"].get("mods", 0)) & (2 | 4 | 8))]
    first_t = ev[0]["t_client_us"] / 1e6 if ev else 0.0
    for e in ev:
        t, d = e["t_client_us"] / 1e6, e["data"]
        if e["type"] in ("copy", "cut"):
            copies[str(d["sha256"])] = "problem_statement" if d.get("source") == "problem_panel" else "internal"
        elif e["type"] == "blur" and d.get("target") == "window":
            away_start = t
        elif e["type"] == "focus" and d.get("target") == "window" and away_start is not None:
            away += t - away_start
            returns.append(t)
            away_start = None
        elif e["type"] == "keydown" and d.get("target", "editor") == "editor" and d.get("cat") in CHAR_CATS and d.get("cat") != "whitespace":
            char_keydowns += 1
        elif e["type"] == "content_change":
            text, cause, n = str(d["text"]), str(d["cause"]), int(d["ins_len"])
            if cause == "typed":
                typed += n
                typed_nonspace += sum(1 for c in text if not c.isspace())
            elif cause in UNTYPED_CAUSES:
                by_cause[cause] = by_cause.get(cause, 0) + n
            if cause == "paste" and n:
                prov = copies.get(_sha(text), "external")
                pastes.append(Paste(t, n, prov))
            if n >= large_insert_chars and not d.get("flush"):
                explained = (
                    (cause == "paste" and any(abs(pt - t) <= 1.0 and pl == n for pt, pl in paste_events))
                    or (cause in ("command", "undo", "redo", "cut") and any(0 <= t - ct <= 1.0 for ct in chord_downs))
                    or t - first_t < 1.0      # restoring the starter or a reload
                )
                if not explained:
                    unexplained.append((t, n, cause))
    if away_start is not None:
        away += (ev[-1]["t_client_us"] / 1e6) - away_start
    coupled = [p.t for p in pastes if p.provenance == "external" and any(0 <= p.t - r <= coupling_s for r in returns)]
    return Insertions(
        typed_chars=typed,
        untyped_chars=sum(by_cause.values()),
        untyped_by_cause=by_cause,
        pastes=pastes,
        external_paste_chars=sum(p.chars for p in pastes if p.provenance == "external"),
        away_seconds=away,
        away_then_external_paste=coupled,
        unexplained_large_inserts=unexplained,
        typed_chars_beyond_keystrokes=max(0, typed_nonspace - char_keydowns),
    )


@dataclass
class SessionSignals:
    keystrokes: list[Keystroke] = field(default_factory=list)
    habits: Habits | None = None
    insertions: Insertions | None = None
    duration_s: float = 0.0


def session_signals(events: Sequence[Event], large_insert_chars: int, coupling_s: float) -> SessionSignals:
    ev = _client(events)
    duration = (ev[-1]["t_client_us"] - ev[0]["t_client_us"]) / 1e6 if len(ev) > 1 else 0.0
    return SessionSignals(editor_keystrokes(events), habits(events), insertions(events, large_insert_chars, coupling_s), duration)
