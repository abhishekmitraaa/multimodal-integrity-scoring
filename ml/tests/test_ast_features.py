"""AST features (SPEC 6.3) on hand-written SYNTHETIC programs and event logs with known answers."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from integrity_ml.ast_features import (
    ERROR, ast_timeline, available, grammar_info, jsd, reference, smoothed, student_baseline, style_distance,
    style_z, summarize, tilt, vocabulary,
)

NESTED = "def f(x):\n    for i in range(x):\n        if i:\n            y = lambda a: a\n    return x\n"


def test_vocabulary_is_the_grammars_named_types_plus_error() -> None:
    v = vocabulary()
    assert list(v) == sorted(v) and len(set(v)) == len(v)
    assert {ERROR, "module", "function_definition", "identifier", "comment"} <= set(v)
    assert "if" not in v and "(" not in v                         # anonymous tokens are not in V
    info = grammar_info()
    assert info["vocabulary_size"] == len(v) and len(info["vocabulary_sha256"]) == 64
    assert info["tree_sitter_python"] == "0.25.0"                 # pinned (ml/pyproject.toml)


def test_counts_nesting_identifiers_and_comments() -> None:
    s = summarize(NESTED)
    assert s.max_nesting == 4                                     # def > for > if > lambda; the "lambda" keyword is not counted again
    assert s.counts["identifier"] == 10 and s.counts["block"] == 3 and s.counts["module"] == 1
    assert s.error_nodes == 0
    # distinct names: f, x, i, range, y, a -> lengths 1,1,1,5,1,1
    assert s.mean_identifier_len == pytest.approx(10 / 6)
    assert s.short_identifier_frac == pytest.approx(5 / 6)
    code = "# hi\nx = 1\n"
    assert summarize(code).comment_frac == pytest.approx(4 / len(code))
    assert summarize("").named_nodes == 1 and summarize("").mean_identifier_len is None   # just the module


def test_syntax_errors_are_tolerated_and_counted() -> None:
    s = summarize("def f(x):\n    return x +\n")
    assert s.error_nodes >= 1 and s.counts.get(ERROR, 0) == s.error_nodes
    assert s.counts["function_definition"] == 1                   # the rest still parses


def test_availability_threshold() -> None:
    s = summarize(NESTED)
    assert available(s, s.named_nodes) and not available(s, s.named_nodes + 1)


def test_smoothing_matches_the_formula() -> None:
    v, alpha = vocabulary(), 0.5
    p = smoothed({"identifier": 3, "module": 1}, alpha)
    n = 4
    assert p.sum() == pytest.approx(1.0)
    assert p[v.index("identifier")] == pytest.approx((3 + alpha) / (n + alpha * len(v)))
    assert p[v.index("block")] == pytest.approx(alpha / (n + alpha * len(v)))
    with pytest.raises(ValueError):
        smoothed({}, 0.0)


def test_tilt_removes_what_the_problem_dictates() -> None:
    r = smoothed(summarize(NESTED).counts, 0.5)
    q = tilt(r, r)                                                # a solution exactly like the reference
    assert np.allclose(q, 1 / len(q))                             # carries no student-specific signal
    assert reference([r, r]) == pytest.approx(r)
    with pytest.raises(ValueError):
        reference([])


def test_jsd_bounds_and_symmetry() -> None:
    a = np.array([1.0, 0.0])
    b = np.array([0.0, 1.0])
    assert jsd(a, a) == 0.0
    assert jsd(a, b) == pytest.approx(1.0)                        # disjoint support, base 2
    p, q = np.array([0.7, 0.3]), np.array([0.4, 0.6])
    assert jsd(p, q) == pytest.approx(jsd(q, p)) and 0 < jsd(p, q) < 1


def test_drift_is_small_for_the_same_style_and_larger_for_a_different_one() -> None:
    r = reference([smoothed(summarize(NESTED).counts, 0.5)])
    own = [tilt(smoothed(summarize(NESTED.replace("x", n)).counts, 0.5), r) for n in ("n", "k")]
    base = student_baseline(own)
    assert base.sum() == pytest.approx(1.0)
    same = jsd(tilt(smoothed(summarize(NESTED.replace("x", "m")).counts, 0.5), r), base)
    other_code = "class A:\n    '''doc'''\n    def g(self):\n        return [v * 2 for v in self.items if v]\n"
    other = jsd(tilt(smoothed(summarize(other_code).counts, 0.5), r), base)
    # Ordering, not size: on programs this short the smoothing over |V| = 124 types dominates
    # (about 0.04 here), one reason AST drift is a weak, fusion-only signal.
    assert same == pytest.approx(0.0, abs=1e-12) and other > 0.01


def test_style_z_and_distance() -> None:
    mean, sd = np.array([2.0, 3.0, 0.5, 0.1]), np.array([1.0, 1.0, 0.0, 0.1])
    z = style_z(np.array([3.0, 5.0, 0.5, 0.1]), mean, sd)
    assert z[0] == 1.0 and z[1] == 2.0 and np.isnan(z[2]) and z[3] == 0.0       # SD 0 -> undefined
    zb = [np.array([0.0, 1.0, np.nan, 0.0]), np.array([0.0, 3.0, np.nan, np.nan])]
    # z_base = [0, 2, nan, 0]; |z - z_base| over defined k = [1, 0, 0] -> 1/3
    assert style_distance(z, zb) == pytest.approx(1 / 3)
    assert style_distance(z, []) is None
    assert style_distance(np.full(4, np.nan), zb) is None


def _snap(t: float, text: str, reason: str = "timer") -> dict[str, Any]:
    return {"type": "snapshot", "t_client_us": int(t * 1e6), "data": {"text": text, "reason": reason}}


def _keys(t: float, n: int) -> list[dict[str, Any]]:
    return [{"type": "keydown", "t_client_us": int((t + i * 0.1) * 1e6), "data": {"code": "KeyA", "target": "editor"}} for i in range(n)]


def test_ast_jump_when_structure_arrives_without_typing() -> None:
    small = "def f(x):\n    return x\n"
    big = small + "".join(f"\ndef g{i}(a, b):\n    if a > b:\n        return [a, b]\n    return (b, a)\n" for i in range(4))
    grow = summarize(big).named_nodes - summarize(small).named_nodes
    assert grow >= 30
    pasted = [_snap(0, small, "segment_start"), *_keys(1, 5), _snap(3, big, "large_insert")]
    tl = ast_timeline(pasted, min_nodes=30, max_keydowns=30, max_snapshots=100)
    assert [(j.t, j.added_nodes, j.keydowns, j.reason) for j in tl.jumps] == [(3.0, grow, 5, "large_insert")]
    assert tl.snapshots == 2 and not tl.truncated and tl.final is not None
    typed = [_snap(0, small, "segment_start"), *_keys(1, 200), _snap(30, big)]
    assert ast_timeline(typed, 30, 30, 100).jumps == []            # same growth, but typed


def test_ast_timeline_skips_identical_snapshots_and_is_bounded() -> None:
    code = "x = 1\n"
    flood = [_snap(i, code) for i in range(50)]
    tl = ast_timeline(flood, 30, 30, max_snapshots=3)
    assert tl.snapshots == 1 and not tl.truncated                 # identical text is parsed once
    distinct = [_snap(i, f"x = {i}\n") for i in range(10)]
    tl = ast_timeline(distinct, 30, 30, max_snapshots=3)
    assert tl.snapshots == 3 and tl.truncated                     # said, not hidden
