"""Fusion pipeline dry run on SYNTHETIC sessions: it runs, keeps the SPEC rules, and labels itself."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from integrity_eval import fusion_dryrun as fd
from integrity_eval.synthetic_sessions import ATTACKS, generate, key_of

CFG = fd._cfg("eval")["fusion_dryrun"]


@pytest.fixture(scope="module")
def small() -> dict[str, Any]:
    return fd.run(CFG, 7, fd.StandInEmbedder(), users=10, outer_folds=2, inner_folds=2, resamples=200)


def _replay(events: list[dict[str, Any]]) -> str:
    text = ""
    for e in events:
        if e["type"] == "content_change":
            d = e["data"]
            text = text[:d["offset"]] + d["text"] + text[d["offset"] + d["del_len"]:]
    return text


def test_generated_sessions_are_consistent_and_labelled() -> None:
    _, sessions = generate(3, fd.practice_texts(), fd.EXAM_TEXT, CFG, seed=1)
    assert {s.label for s in sessions} == {"practice", "genuine", *ATTACKS}
    for s in sessions:
        times = [e["t_client_us"] for e in s.events]
        assert times == sorted(times)
        final = next(e["data"]["text"] for e in reversed(s.events) if e["type"] == "snapshot")
        assert _replay(s.events) == final                     # content changes carry true offsets
        assert s.uid.startswith("SYN-")
    assert all(s.onset_s is not None for s in sessions if s.label in ATTACKS)
    with pytest.raises(ValueError, match="two"):
        generate(1, fd.practice_texts(), fd.EXAM_TEXT, CFG, seed=1)
    assert key_of("a") == ("KeyA", "letter") and key_of("(")[1] == "bracket" and key_of("\n") == ("Enter", "whitespace")


def test_ticks_follow_spec_8_1() -> None:
    _, sessions = generate(2, fd.practice_texts(), fd.EXAM_TEXT, CFG, seed=2)
    a1 = next(s for s in sessions if s.label == "A1")
    ticks = fd.tick_times(a1.events, every=35, first_after=70, max_interval_s=30)
    assert ticks == sorted(ticks) and np.diff(ticks).max() <= 30 + 1e-9
    paste_t = next(e["t_client_us"] / 1e6 for e in a1.events if e["type"] == "paste")
    assert paste_t in ticks                                    # every paste is a tick


def test_dry_run_keeps_the_rules(small: dict[str, Any]) -> None:
    assert small["synthetic"] is True and "SYNTHETIC" in small["banner"]
    for f in small["folds"]:
        for name in fd.INPUTS:
            assert f["weights"][name] <= 0.0                   # SPEC 7.4: more anomaly never raises S
        assert f["c"] in (0.01, 0.1, 1.0, 10.0) and 0 < f["tau"] < 1
    assert set(small["sessions"]) == {"genuine", *ATTACKS}
    assert all(v["sessions"] == 10 for v in small["sessions"].values())
    cal = small["calibration"]
    assert 0 <= cal["ece"] <= 1 and 0 <= cal["brier"] <= 1 and sum(b["n"] for b in cal["reliability"]) == small["coverage"]["ticks"]


def test_dry_run_is_reproducible(small: dict[str, Any]) -> None:
    again = fd.run(CFG, 7, fd.StandInEmbedder(), users=10, outer_folds=2, inner_folds=2, resamples=200)
    assert again["sessions"] == small["sessions"] and again["folds"] == small["folds"]


def test_report_and_cli_say_synthetic(small: dict[str, Any], tmp_path: Any) -> None:
    md = fd.render(small, "manifest")
    assert md.count("SYNTHETIC") >= 3 and "never report these numbers" in md
    with pytest.raises(SystemExit):
        fd.main(["--out", str(tmp_path / "fusion_report.md"), "--users", "4"])     # name must say synthetic


def test_calibration_math() -> None:
    p = np.array([0.05, 0.05, 0.95, 0.95])
    y = np.array([0.0, 0.0, 1.0, 1.0])
    c = fd.calibration(p, y)
    assert c["ece"] == pytest.approx(0.05) and c["brier"] == pytest.approx(0.0025)
