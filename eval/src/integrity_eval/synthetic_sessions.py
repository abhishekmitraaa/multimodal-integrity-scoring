"""SYNTHETIC coding sessions (D4) for the fusion pipeline dry run. Never a person; never a result.

Each synthetic user has a typing profile (speed, rhythm spread, per-key-pair habits, hold times,
pauses, typos). Sessions are written in the stored-event shape the server keeps (keydown/keyup,
content_change, paste, blur/focus, snapshot, run, submit), so every feature runs through the same
code as on real data.

- practice: the three practice solutions, copy-typed (the baseline, D-035);
- genuine exam: the exam solution typed by the same user while composing (more and longer pauses,
  more corrections), which is why genuine exams differ from the baseline;
- A1 external paste: the user types the start, leaves the window, then pastes the rest;
- A3b auto-typer: the solution injected at a near-constant rhythm;
- A4 copy-type by someone else: another synthetic user types the solution.

What this generator does NOT model, so the dry run cannot say anything about it: coding style
(every user types the same text, so the AST inputs carry no signal), real keyboards and editors,
real cheating behaviour. It tests that the pipeline runs and that its pieces fit together.
"""

from __future__ import annotations

import hashlib
import math
import zlib
from dataclasses import dataclass, field
from typing import Any

import numpy as np

ATTACKS = ("A1", "A3b", "A4")
_SYMBOL_CODES = {
    "(": ("Digit9", "bracket"), ")": ("Digit0", "bracket"), "[": ("BracketLeft", "bracket"),
    "]": ("BracketRight", "bracket"), "{": ("BracketLeft", "bracket"), "}": ("BracketRight", "bracket"),
    "=": ("Equal", "symbol"), "+": ("Equal", "symbol"), "-": ("Minus", "symbol"), "_": ("Minus", "symbol"),
    ":": ("Semicolon", "symbol"), ",": ("Comma", "symbol"), ".": ("Period", "symbol"), "'": ("Quote", "symbol"),
    '"': ("Quote", "symbol"), "%": ("Digit5", "symbol"), "<": ("Comma", "symbol"), ">": ("Period", "symbol"),
    "#": ("Digit3", "symbol"), "*": ("Digit8", "symbol"), "/": ("Slash", "symbol"),
}


def key_of(ch: str) -> tuple[str, str]:
    """(KeyboardEvent.code, category) for a character typed on a US layout (Shift not modelled)."""
    if ch.isalpha() and ch.isascii():
        return f"Key{ch.upper()}", "letter"
    if ch.isdigit():
        return f"Digit{ch}", "digit"
    if ch == " ":
        return "Space", "whitespace"
    if ch == "\n":
        return "Enter", "whitespace"
    return _SYMBOL_CODES.get(ch, ("Backquote", "symbol"))


def _unit_normal(*parts: object) -> float:
    """A deterministic N(0, 1) draw from a key (stable across runs; Python's hash() is not)."""
    u1 = (zlib.crc32(repr(parts).encode()) + 0.5) / 2**32
    u2 = (zlib.crc32(repr(parts[::-1]).encode() + b"#") + 0.5) / 2**32
    return math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)


@dataclass(frozen=True)
class Typist:
    uid: str
    flight_ms: float          # median press-to-press
    hold_ms: float
    flight_log_sd: float      # within-user noise
    hold_log_sd: float
    pair_log_sd: float        # this user's deviation per key pair (their "habit")
    pause_p: float            # chance of a thinking pause before a line
    typo_p: float             # chance per character of a typo, then Backspace
    constant: bool = False    # an auto-typer: no pauses, no typos, near-constant timing

    def flight(self, prev: str, cur: str, rng: np.random.Generator) -> float:
        if self.constant:
            return self.flight_ms * (1 + rng.uniform(-0.01, 0.01)) / 1000
        shared = 0.3 * _unit_normal("pair", prev, cur)                       # some pairs are harder for everyone
        own = self.pair_log_sd * _unit_normal(self.uid, prev, cur)           # and this user has their own habits
        return max(0.03, self.flight_ms * math.exp(shared + own + rng.normal(0, self.flight_log_sd)) / 1000)

    def hold(self, key: str, rng: np.random.Generator) -> float:
        if self.constant:
            return self.hold_ms * (1 + rng.uniform(-0.01, 0.01)) / 1000
        return max(0.02, self.hold_ms * math.exp(0.15 * _unit_normal("hold", key) + 0.2 * _unit_normal(self.uid, key)
                                                 + rng.normal(0, self.hold_log_sd)) / 1000)


def sample_typist(uid: str, rng: np.random.Generator, cfg: dict[str, Any]) -> Typist:
    return Typist(
        uid=uid,
        flight_ms=cfg["base_flight_ms"] * math.exp(rng.normal(0, cfg["user_speed_log_sd"])),
        hold_ms=cfg["base_hold_ms"] * math.exp(rng.normal(0, cfg["user_hold_log_sd"])),
        flight_log_sd=cfg["noise_flight_log_sd"] * math.exp(rng.normal(0, 0.2)),
        hold_log_sd=cfg["noise_hold_log_sd"],
        pair_log_sd=cfg["user_pair_log_sd"],
        pause_p=float(rng.uniform(*cfg["pause_p_range"])),
        typo_p=float(rng.uniform(*cfg["typo_p_range"])),
    )


def auto_typer(cfg: dict[str, Any]) -> Typist:
    return Typist("auto-typer", cfg["auto_typer_flight_ms"], cfg["auto_typer_hold_ms"], 0, 0, 0, 0, 0, constant=True)


@dataclass
class Session:
    uid: str
    kind: str                 # practice | exam
    label: str                # practice | genuine | A1 | A3b | A4
    problem_id: str
    events: list[dict[str, Any]] = field(default_factory=list)
    onset_s: float | None = None          # attack onset (client seconds); None = no attack


class _Writer:
    """Writes one session's events in time order, keeping the document so changes carry true offsets."""

    def __init__(self, rng: np.random.Generator, t0: float = 1.0, snapshot_every_s: float = 10.0) -> None:
        self.rng = rng
        self.t = t0
        self.text = ""
        self.version = 0
        self.events: list[dict[str, Any]] = []
        self.snapshot_every_s = snapshot_every_s
        self.last_snapshot_t = t0
        self.last_snapshot_text: str | None = None

    def _ev(self, etype: str, data: dict[str, Any], t: float | None = None) -> None:
        self.events.append({"type": etype, "t_client_us": int(round((self.t if t is None else t) * 1e6)), "data": data})

    def snapshot(self, reason: str) -> None:
        self._ev("snapshot", {"version_id": self.version, "reason": reason, "len": len(self.text),
                              "sha256": hashlib.sha256(self.text.encode()).hexdigest(), "text": self.text})
        self.last_snapshot_t, self.last_snapshot_text = self.t, self.text

    def _change(self, offset: int, del_len: int, ins: str, cause: str, t: float) -> None:
        self.version += 1
        line = self.text.count("\n", 0, offset) + 1
        col = offset - (self.text.rfind("\n", 0, offset) + 1) + 1
        self._ev("content_change", {
            "version_id": self.version, "idx": 0, "n": 1, "offset": offset, "del_len": del_len, "ins_len": len(ins),
            "text": ins, "start_line": line, "start_col": col, "end_line": line, "end_col": col + del_len, "cause": cause,
            "undo": False, "redo": False, "flush": False}, t)
        self.text = self.text[:offset] + ins + self.text[offset + del_len:]

    def _key(self, typist: Typist, code: str, cat: str, prev: str, ins: str | None) -> None:
        self.t += typist.flight(prev, code, self.rng)
        down = {"code": code, "cat": cat, "rep": False, "mods": 0, "target": "editor"}
        self._ev("keydown", down)
        if ins is None:                                  # Backspace
            self._change(len(self.text) - 1, 1, "", "typed", self.t + 0.004)
        else:
            self._change(len(self.text), 0, ins, "typed", self.t + 0.004)
        self._ev("keyup", {"code": code, "cat": cat, "target": "editor"}, self.t + typist.hold(code, self.rng))
        if self.t - self.last_snapshot_t >= self.snapshot_every_s and self.text != self.last_snapshot_text:
            self.snapshot("timer")

    def type_text(self, typist: Typist, text: str, pause_scale: float = 1.0, typo_scale: float = 1.0,
                  pause_s: tuple[float, float] = (2.0, 5.0)) -> None:
        prev = "Enter"
        for ch in text:
            if not typist.constant and (prev == "Enter" and self.rng.random() < min(1.0, typist.pause_p * pause_scale)):
                self.t += float(self.rng.uniform(*pause_s))                   # thinking before a line
            code, cat = key_of(ch)
            if not typist.constant and ch.isalpha() and self.rng.random() < typist.typo_p * typo_scale:
                wrong = "x" if ch != "x" else "z"
                self._key(typist, key_of(wrong)[0], "letter", prev, wrong)
                self._key(typist, "Backspace", "backspace", key_of(wrong)[0], None)
                prev = "Backspace"
            self._key(typist, code, cat, prev, ch)
            prev = code

    def away(self, seconds: float) -> None:
        self.t += 0.5
        self._ev("blur", {"target": "window"})
        self.t += seconds
        self._ev("focus", {"target": "window"})

    def paste(self, text: str) -> None:
        self.t += 1.0
        self._ev("paste", {"len": len(text)})
        self._change(len(self.text), 0, text, "paste", self.t + 0.002)
        self.snapshot("large_insert")

    def finish(self) -> list[dict[str, Any]]:
        self.t += 1.0
        self._ev("run", {"kind": "test", "n_tests": 3, "n_passed": 3, "status": "ok", "dur_ms": 40, "version_id": self.version})
        self.snapshot("submit")
        self._ev("submit", {"version_id": self.version, "sha256": hashlib.sha256(self.text.encode()).hexdigest()})
        return sorted(self.events, key=lambda e: e["t_client_us"])          # keyups may follow the next keydown


def generate(users: int, practice_texts: dict[str, str], exam_text: str, cfg: dict[str, Any],
             seed: int) -> tuple[list[Typist], list[Session]]:
    """users synthetic users, each with practice sessions, a genuine exam and one session per attack."""
    if users < 2:
        raise ValueError("A4 needs at least two synthetic users (someone else types the exam)")
    rng = np.random.default_rng(seed)
    typists = [sample_typist(f"SYN-U{i:03d}", rng, cfg) for i in range(users)]
    sessions: list[Session] = []
    for i, u in enumerate(typists):
        for pid, text in practice_texts.items():
            w = _Writer(rng)
            w.snapshot("segment_start")
            w.type_text(u, text)
            sessions.append(Session(u.uid, "practice", "practice", pid, w.finish()))
        composing = dict(pause_scale=cfg["composing_pause_scale"], typo_scale=cfg["composing_typo_scale"],
                         pause_s=tuple(cfg["composing_pause_s"]))
        w = _Writer(rng)
        w.snapshot("segment_start")
        w.type_text(u, exam_text, **composing)
        sessions.append(Session(u.uid, "exam", "genuine", "exam", w.finish()))

        # A1: types the start, leaves the window, pastes the rest from outside the editor
        cut = int(len(exam_text) * cfg["a1_typed_share"])
        cut = exam_text.rfind("\n", 0, cut) + 1 or cut
        w = _Writer(rng)
        w.snapshot("segment_start")
        w.type_text(u, exam_text[:cut], **composing)
        onset = w.t
        w.away(float(rng.uniform(*cfg["a1_away_s"])))
        w.paste(exam_text[cut:])
        sessions.append(Session(u.uid, "exam", "A1", "exam", w.finish(), onset_s=onset))

        # A3b: an auto-typer injects the whole solution
        w = _Writer(rng)
        w.snapshot("segment_start")
        start = w.t
        w.type_text(auto_typer(cfg), exam_text)
        sessions.append(Session(u.uid, "exam", "A3b", "exam", w.finish(), onset_s=start))

        # A4: someone else copy-types the solution
        other = typists[(i + 1 + int(rng.integers(users - 1))) % users]
        w = _Writer(rng)
        w.snapshot("segment_start")
        start = w.t
        w.type_text(other, exam_text)
        sessions.append(Session(u.uid, "exam", "A4", "exam", w.finish(), onset_s=start))
    return typists, sessions
