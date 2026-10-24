"""TypeNet input matrices (TypeNet §4.1–4.2; p2_protocol.md §2–3).

One row per keystroke: [keycode / 255, HL, IL, PL, RL], latencies in seconds, no clipping.
Latencies are computed on the whole sequence and then truncated to M, so only the sequence's real
last keystroke has zero inter-key features. Shorter sequences are zero-padded at the end, and the
true length is returned for masking.

Aalto gives integer keycodes. Our capture stores KeyboardEvent.code, so `legacy_keycode` maps it
to the US-layout legacy keyCode (deviation 11).
"""

from __future__ import annotations

from typing import Callable, Sequence

import numpy as np
from numpy.typing import NDArray

from .keystroke import Keystroke, latencies

_NAMED = {
    "Space": 32, "Enter": 13, "NumpadEnter": 13, "Backspace": 8, "Tab": 9, "Escape": 27, "Delete": 46,
    "ShiftLeft": 16, "ShiftRight": 16, "ControlLeft": 17, "ControlRight": 17, "AltLeft": 18, "AltRight": 18,
    "MetaLeft": 91, "MetaRight": 92, "CapsLock": 20, "ArrowLeft": 37, "ArrowUp": 38, "ArrowRight": 39,
    "ArrowDown": 40, "Home": 36, "End": 35, "PageUp": 33, "PageDown": 34, "Insert": 45,
    "Semicolon": 186, "Equal": 187, "Comma": 188, "Minus": 189, "Period": 190, "Slash": 191,
    "Backquote": 192, "BracketLeft": 219, "Backslash": 220, "BracketRight": 221, "Quote": 222,
}


def legacy_keycode(code: str) -> int:
    """US-layout legacy keyCode for a KeyboardEvent.code; 0 if unknown."""
    if len(code) == 4 and code.startswith("Key") and code[3].isalpha():
        return ord(code[3].upper())
    if len(code) == 6 and code.startswith("Digit") and code[5].isdigit():
        return ord(code[5])
    if code.startswith("F") and code[1:].isdigit() and 1 <= int(code[1:]) <= 12:
        return 111 + int(code[1:])
    return _NAMED.get(code, 0)


def typenet_matrix(
    keystrokes: Sequence[Keystroke], m: int, keycode: Callable[[str], int] = legacy_keycode,
) -> tuple[NDArray[np.float32], int]:
    """(M x 5 float32 matrix, true length <= M). Keystrokes are ordered by press time first."""
    ks = sorted(keystrokes, key=lambda k: (k.down_us, k.up_us))
    out = np.zeros((m, 5), dtype=np.float32)
    if not ks:
        return out, 0
    lat = latencies(ks)
    n = min(len(ks), m)
    out[:n, 0] = [keycode(k.code) / 255.0 for k in ks[:n]]
    out[:n, 1] = lat.hl_ms[:n] / 1000.0
    inter = min(n, len(ks) - 1)
    out[:inter, 2] = lat.il_ms[:inter] / 1000.0
    out[:inter, 3] = lat.pl_ms[:inter] / 1000.0
    out[:inter, 4] = lat.rl_ms[:inter] / 1000.0
    return out, n
