"""P2 D1 helpers on hand-built SYNTHETIC keystrokes."""

from __future__ import annotations

import numpy as np
import pytest

from integrity_eval.d1_aalto import keycode_of
from integrity_eval.p2_d1 import PUBLISHED, band, keystrokes_from_matrix
from integrity_ml.keystroke import Keystroke, latencies
from integrity_ml.sequences import typenet_matrix


def test_bands_match_the_protocol() -> None:
    assert band(4.5) == (2.25, 6.75)
    assert band(1.2) == pytest.approx((0.2, 2.2))
    assert PUBLISHED[70][10] == 1.2 and PUBLISHED[50][5] == 2.2


def test_matrix_round_trip_preserves_codes_and_latencies() -> None:
    t = 1_473_275_372_000_000   # absolute µs, as in D1
    seq = [Keystroke("16", t, t + 151_000), Keystroke("87", t + 71_000, t + 191_000), Keystroke("65", t + 247_000, t + 391_000)]
    mat, n = typenet_matrix(seq, 70, keycode=keycode_of)
    back = keystrokes_from_matrix(mat.astype(np.float16), n)
    assert [k.code for k in back] == ["16", "87", "65"]
    a, b = latencies(seq), latencies(back)
    for x, y in ((a.hl_ms, b.hl_ms), (a.pl_ms, b.pl_ms), (a.il_ms, b.il_ms), (a.rl_ms, b.rl_ms)):
        np.testing.assert_allclose(x, y, atol=0.1)   # float16 storage: well under the data's 1 ms resolution
