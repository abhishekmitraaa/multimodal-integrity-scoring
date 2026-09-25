"""Keystroke pairing and TypeNet latencies (SPEC 6.1).

A keystroke is a non-repeat keydown with its matched keyup. A keyup matches the most recent
unmatched keydown with the same code, which handles rollover. Unmatched events are dropped and
counted. Auto-repeat keydowns are counted and excluded; the held key's final keyup still ends it.

Latencies between consecutive keystrokes i and i+1, ordered by press time (TypeNet §4.1, Fig. 1):
HL = up_i - down_i, PL = down_{i+1} - down_i, IL = down_{i+1} - up_i (negative when the keys
overlap), RL = up_{i+1} - up_i.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Sequence

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class KeyEvent:
    type: Literal["keydown", "keyup"]
    code: str
    t_us: int
    rep: bool = False


@dataclass(frozen=True)
class Keystroke:
    code: str
    down_us: int
    up_us: int


@dataclass(frozen=True)
class PairingStats:
    keystrokes: int
    repeats: int
    unmatched_keydowns: int
    unmatched_keyups: int


@dataclass(frozen=True)
class Latencies:
    """All in milliseconds. hl has one value per keystroke; the others one per consecutive pair."""

    hl_ms: FloatArray
    pl_ms: FloatArray
    il_ms: FloatArray
    rl_ms: FloatArray


def pair_keystrokes(events: Iterable[KeyEvent]) -> tuple[list[Keystroke], PairingStats]:
    """Pair keydowns with keyups. Events must be in dispatch order."""
    open_downs: dict[str, list[int]] = {}
    keystrokes: list[Keystroke] = []
    repeats = unmatched_keyups = 0
    for event in events:
        if event.type == "keydown":
            if event.rep:
                repeats += 1
            else:
                open_downs.setdefault(event.code, []).append(event.t_us)
            continue
        stack = open_downs.get(event.code)
        if not stack:
            unmatched_keyups += 1
            continue
        keystrokes.append(Keystroke(event.code, stack.pop(), event.t_us))
    keystrokes.sort(key=lambda k: (k.down_us, k.up_us))
    unmatched_keydowns = sum(len(stack) for stack in open_downs.values())
    return keystrokes, PairingStats(len(keystrokes), repeats, unmatched_keydowns, unmatched_keyups)


def latencies(keystrokes: Sequence[Keystroke]) -> Latencies:
    down = np.array([k.down_us for k in keystrokes], dtype=np.float64) / 1000.0
    up = np.array([k.up_us for k in keystrokes], dtype=np.float64) / 1000.0
    return Latencies(
        hl_ms=up - down,
        pl_ms=np.diff(down),
        il_ms=down[1:] - up[:-1],
        rl_ms=np.diff(up),
    )
