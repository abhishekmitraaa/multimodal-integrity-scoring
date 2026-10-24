"""TypeNet input matrices and the legacy keycode table, on hand-built SYNTHETIC keystrokes."""

from __future__ import annotations

import numpy as np
import pytest

from integrity_ml.keystroke import Keystroke
from integrity_ml.sequences import legacy_keycode, typenet_matrix


def ks(code: str, down_ms: float, up_ms: float) -> Keystroke:
    return Keystroke(code, round(down_ms * 1000), round(up_ms * 1000))


@pytest.mark.parametrize("code,expected", [
    ("KeyA", 65), ("KeyZ", 90), ("Digit0", 48), ("Digit9", 57), ("Space", 32), ("Enter", 13),
    ("Backspace", 8), ("ShiftLeft", 16), ("BracketLeft", 219), ("F1", 112), ("F12", 123), ("Weird", 0),
])
def test_legacy_keycode(code: str, expected: int) -> None:
    assert legacy_keycode(code) == expected


def test_matrix_values_units_and_padding() -> None:
    seq = [ks("KeyA", 0, 100), ks("KeyB", 150, 230), ks("KeyC", 300, 350)]
    x, n = typenet_matrix(seq, m=5)
    assert x.shape == (5, 5) and x.dtype == np.float32 and n == 3
    np.testing.assert_allclose(x[0], [65 / 255, 0.100, 0.050, 0.150, 0.130], rtol=1e-6)   # keycode, HL, IL, PL, RL
    np.testing.assert_allclose(x[1], [66 / 255, 0.080, 0.070, 0.150, 0.120], rtol=1e-6)
    np.testing.assert_allclose(x[2], [67 / 255, 0.050, 0, 0, 0], rtol=1e-6)               # real last keystroke
    assert not x[3:].any()                                                                  # zero padding


def test_truncation_keeps_the_next_key_latencies() -> None:
    seq = [ks("KeyA", 0, 100), ks("KeyB", 150, 230), ks("KeyC", 300, 350)]
    x, n = typenet_matrix(seq, m=2)
    assert n == 2
    assert x[1, 3] == pytest.approx(0.150)   # PL to the dropped third key is kept


def test_negative_il_and_empty() -> None:
    x, _ = typenet_matrix([ks("ShiftLeft", 0, 200), ks("KeyA", 50, 120)], m=2)
    assert x[0, 2] == pytest.approx(-0.150)
    empty, n = typenet_matrix([], m=3)
    assert n == 0 and not empty.any()
