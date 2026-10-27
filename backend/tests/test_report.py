"""Evidence report (D-036) on hand-built SYNTHETIC sessions, with a stand-in keystroke model."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np
import pytest
import yaml

from integrity_backend.report import build_report
from integrity_backend.settings import REPO_ROOT

RULES = yaml.safe_load((REPO_ROOT / "config" / "scoring.yaml").read_text(encoding="utf-8"))["report"]
FEATURES_CFG = yaml.safe_load((REPO_ROOT / "config" / "features.yaml").read_text(encoding="utf-8"))
AST = FEATURES_CFG["ast"]
CFG = {"report": RULES, "m": 70, "stride": 35, "clip_s": 1.5, "g_min": 5, "large_insert_chars": 32, "coupling_s": 10.0,
       "ast": AST, "process": FEATURES_CFG["process"]}


@dataclass
class Ref:
    g: int
    genuine: dict[str, float] = field(default_factory=lambda: {"p95": 0.05})
    eer_threshold: float = 0.06


class FakeModel:
    """Embedding = mean press-to-press interval and mean hold of the window (seconds)."""

    def embed(self, windows: Sequence[np.ndarray]) -> np.ndarray:
        return np.array([[w[:-1, 3].mean(), w[:, 1].mean()] for w in windows], dtype=np.float32)

    def reference(self, g: int) -> Ref:
        return Ref(g)


class Log:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.t = 1_000_000
        self.pos = 0                      # end of the document: every insertion goes there

    def add(self, etype: str, data: dict[str, Any], t: int | None = None) -> None:
        self.events.append({"type": etype, "t_client_us": self.t if t is None else t, "data": data})

    def change(self, text: str, cause: str) -> dict[str, Any]:
        """A schema-complete content_change inserting text at the end."""
        d = {"version_id": len(self.events), "idx": 0, "n": 1, "offset": self.pos, "del_len": 0, "ins_len": len(text),
             "text": text, "start_line": 1, "start_col": self.pos + 1, "end_line": 1, "end_col": self.pos + 1,
             "cause": cause, "undo": False, "redo": False, "flush": False}
        self.pos += len(text)
        return d

    def type(self, n: int, gap_ms: float, hold_ms: float = 80, jitter: float = 0.3, seed: int = 0) -> "Log":
        rng = np.random.default_rng(seed)
        for i in range(n):
            self.t += int(gap_ms * 1000 * (1 + jitter * rng.uniform(-1, 1)))
            key = {"code": "KeyA" if i % 2 else "KeyS", "cat": "letter", "rep": False, "mods": 0, "target": "editor"}
            self.add("keydown", key)
            self.add("content_change", self.change("a", "typed"), self.t + 300)
            self.add("keyup", key, self.t + int(hold_ms * 1000))
        return self

    def paste(self, text: str, after_away_s: float | None = None) -> "Log":
        if after_away_s is not None:
            self.add("blur", {"target": "window"})
            self.t += int(after_away_s * 1e6)
            self.add("focus", {"target": "window"})
        self.t += 2_000_000
        self.add("paste", {"len": len(text)})
        self.add("content_change", self.change(text, "paste"))
        return self


def session(kind: str, log: Log, sid: str, closed: bool = True) -> dict[str, Any]:
    return {"session_id": sid, "kind": kind, "problem_id": f"{kind}_x", "closed": closed, "events": log.events}


def practice(n_sessions: int = 3, keys: int = 140, gap_ms: float = 180) -> list[dict[str, Any]]:
    return [session("practice", Log().type(keys, gap_ms, seed=i), f"p{i}") for i in range(n_sessions)]


def exam_state(report: dict[str, Any]) -> str:
    return str(report["exams"][0]["state"])


def finding(report: dict[str, Any], fid: str) -> dict[str, str]:
    return next(f for f in report["exams"][0]["findings"] if f["id"] == fid)


def test_same_typist_no_paste_gets_no_review_flags() -> None:
    r = build_report("DEV-1", practice() + [session("exam", Log().type(210, 180, seed=9), "e")], FakeModel(), "", CFG)
    assert r["baseline"]["status"] == "ready" and r["baseline"]["windows"] == 6
    assert exam_state(r) == "no_review_flags" and r["overall"]["state"] == "no_review_flags"
    assert finding(r, "keystroke")["status"] == "ok"
    assert r["exams"][0]["keystroke"]["windows"][0]["t"] > 0       # seconds since the exam started


def test_different_rhythm_is_flagged() -> None:
    r = build_report("DEV-2", practice() + [session("exam", Log().type(210, 400, hold_ms=150, seed=9), "e")], FakeModel(), "", CFG)
    assert finding(r, "keystroke")["status"] == "flag"
    assert exam_state(r) == "review" and any("Typing rhythm" in x for x in r["overall"]["reasons"])


def test_external_paste_after_leaving_the_window_is_flagged() -> None:
    code = "def rle(s):\n    out = []\n    return ''.join(out)\n" * 2
    r = build_report("DEV-3", practice() + [session("exam", Log().type(80, 180).paste(code, after_away_s=30), "e")], FakeModel(), "", CFG)
    ids = {f["id"] for f in r["exams"][0]["findings"] if f["status"] == "flag"}
    assert {"external_paste", "away_then_paste", "untyped"} <= ids
    assert r["exams"][0]["pastes"][0]["provenance"] == "external"


def test_internal_paste_is_not_flagged() -> None:
    moved = "    count = 1\n" * 4
    log = Log().type(210, 180, seed=9)
    log.add("cut", {"source": "editor", "len": len(moved), "sha256": hashlib.sha256(moved.encode()).hexdigest()})
    log.paste(moved)
    r = build_report("DEV-4", practice() + [session("exam", log, "e")], FakeModel(), "", CFG)
    assert finding(r, "external_paste")["status"] == "ok" and exam_state(r) == "no_review_flags"


def test_auto_typer_rhythm_is_flagged() -> None:
    r = build_report("DEV-5", practice() + [session("exam", Log().type(210, 180, jitter=0.0), "e")], FakeModel(), "", CFG)
    assert finding(r, "machine_rhythm")["status"] == "flag"


def test_not_enough_practice_means_insufficient_data() -> None:
    r = build_report("DEV-6", practice(n_sessions=1, keys=100) + [session("exam", Log().type(210, 180), "e")], FakeModel(), "", CFG)
    assert r["baseline"]["status"] == "insufficient" and r["baseline"]["windows"] == 1
    assert finding(r, "keystroke")["status"] == "unavailable" and exam_state(r) == "insufficient_data"


def test_no_model_installed_is_reported_not_hidden() -> None:
    r = build_report("DEV-7", practice() + [session("exam", Log().type(210, 180), "e")], None, "model missing", CFG)
    assert r["model"] == {"available": False, "note": "model missing"}
    assert "not installed" in finding(r, "keystroke")["detail"]


def test_open_practice_does_not_count_and_no_exam_yet() -> None:
    sessions = practice()
    sessions[0]["closed"] = False
    r = build_report("DEV-8", sessions, FakeModel(), "", CFG)
    assert len(r["baseline"]["practice_sessions"]) == 2 and r["overall"]["state"] == "no_exam_yet"
    assert r["false_flag_note"] and r["no_score_note"]


@pytest.mark.parametrize("state", ["review", "no_review_flags"])
def test_unclosed_exam_does_not_drive_the_overall_state(state: str) -> None:
    exam = Log().type(80, 180).paste("x" * 200, after_away_s=30) if state == "review" else Log().type(210, 180)
    r = build_report("DEV-9", practice() + [session("exam", exam, "e", closed=False)], FakeModel(), "", CFG)
    assert exam_state(r) == state and r["overall"]["state"] == "no_exam_yet"


# ---- the baseline check (D-038) --------------------------------------------------------------

def check(log: Log, sid: str = "c") -> dict[str, Any]:
    return {**session("practice", log, sid), "stage": "check"}


def test_check_by_the_same_typer_confirms_the_baseline_and_sets_a_personal_line() -> None:
    r = build_report("DEV-C1", practice() + [check(Log().type(140, 180, seed=21)), session("exam", Log().type(210, 180, seed=9), "e")],
                     FakeModel(), "", CFG)
    c = r["baseline"]["check"]
    assert c["status"] == "confirmed" and c["personal_threshold"] is not None
    assert [p["problem_id"] for p in r["baseline"]["practice_sessions"]] == ["practice_x"] * 3   # the check is held out
    ks = r["exams"][0]["keystroke"]
    assert ks["threshold"] == max(ks["population_threshold"], ks["personal_threshold"])
    assert exam_state(r) == "no_review_flags"


def test_check_that_does_not_match_goes_to_review_and_never_switches_detection_off() -> None:
    # A student could type the check deliberately differently, hoping to turn the typing comparison off.
    r = build_report("DEV-C2", practice() + [check(Log().type(140, 400, hold_ms=150, seed=21)),
                                             session("exam", Log().type(210, 400, hold_ms=150, seed=9), "e")], FakeModel(), "", CFG)
    assert r["baseline"]["check"]["status"] == "not_confirmed"
    assert finding(r, "baseline_check")["status"] == "flag"
    assert finding(r, "keystroke")["status"] == "flag"                 # still compared with the reference line
    assert r["exams"][0]["keystroke"]["personal_threshold"] is None
    assert exam_state(r) == "review"


def test_detection_a_different_typer_in_the_exam_is_flagged_after_a_confirmed_check() -> None:
    r = build_report("DEV-C3", practice() + [check(Log().type(140, 180, seed=21)),
                                             session("exam", Log().type(210, 400, hold_ms=150, seed=9), "e")], FakeModel(), "", CFG)
    assert r["baseline"]["check"]["status"] == "confirmed"
    assert finding(r, "keystroke")["status"] == "flag" and exam_state(r) == "review"


def test_no_check_yet_uses_the_reference_line_and_says_so() -> None:
    r = build_report("DEV-C4", practice() + [session("exam", Log().type(210, 180, seed=9), "e")], FakeModel(), "", CFG)
    assert r["baseline"]["check"]["status"] == "not_done"
    assert "No usable baseline check" in finding(r, "keystroke")["detail"]


def test_personal_line_is_capped() -> None:
    # A sloppy-but-matching check must not widen the personal line beyond check_cap x the reference line.
    ref = 0.05
    big = {**CFG, "report": {**RULES, "check_mismatch_share": 1.01}}       # accept any check, to reach the cap
    r = build_report("DEV-C5", practice() + [check(Log().type(140, 900, hold_ms=300, seed=21)),
                                             session("exam", Log().type(210, 180, seed=9), "e")], FakeModel(), "", big)
    assert r["baseline"]["check"]["personal_threshold"] == pytest.approx(ref * RULES["check_cap"], abs=1e-3)   # stored to 3 decimals


def test_a_check_taken_after_the_exam_started_does_not_count_and_only_the_first_check_counts() -> None:
    late = {**check(Log().type(140, 180, seed=21), "late"), "closed_at": 200.0}
    exam = {**session("exam", Log().type(210, 180, seed=9), "e"), "created_at": 100.0}
    r = build_report("DEV-C6", practice() + [late, exam], FakeModel(), "", CFG)
    assert r["baseline"]["check"]["status"] == "confirmed"
    assert r["exams"][0]["keystroke"]["personal_threshold"] is None        # check closed after the exam started

    first = {**check(Log().type(140, 400, hold_ms=150, seed=21), "first"), "closed_at": 10.0}
    retake = {**check(Log().type(140, 180, seed=22), "retake"), "closed_at": 20.0}
    r = build_report("DEV-C7", practice() + [first, retake], FakeModel(), "", CFG)
    assert r["baseline"]["check"]["status"] == "not_confirmed"              # a retake cannot replace the first check


def test_code_structure_without_typing_is_shown_as_evidence_not_a_flag() -> None:
    small = "def rle(s):\n    return s\n"
    big = small + "".join(f"\ndef g{i}(a, b):\n    if a > b:\n        return [a, b]\n    return (b, a)\n" for i in range(4))
    log = Log()
    log.add("snapshot", {"text": small, "reason": "segment_start"})
    log.type(210, 180, seed=9)
    log.add("snapshot", {"text": small, "reason": "timer"})
    log.t += 5_000_000
    log.add("snapshot", {"text": big, "reason": "large_insert"})       # appears with no key presses in between
    r = build_report("DEV-AST", practice() + [session("exam", log, "e")], FakeModel(), "", CFG)
    f = finding(r, "ast_jump")
    assert f["status"] == "info" and f["detail"].startswith("1 time(s)")
    assert exam_state(r) == "no_review_flags"                          # evidence for the reviewer, never a flag by itself
    jump = r["exams"][0]["ast_jumps"][0]
    assert jump["keydowns"] == 0 and jump["added_nodes"] >= AST["jump_min_nodes"] and jump["t"] > 0
    plain = build_report("DEV-AST2", practice() + [session("exam", Log().type(210, 180, seed=9), "e")], FakeModel(), "", CFG)
    assert finding(plain, "ast_jump")["detail"] == "None." and plain["exams"][0]["ast_jumps"] == []


def test_process_features_for_the_exam_and_the_practice_baseline() -> None:
    r = build_report("DEV-PROC", practice() + [session("exam", Log().type(210, 180, seed=9), "e")], FakeModel(), "", CFG)
    proc = r["exams"][0]["process"]
    assert set(proc["exam"]) == set(proc["baseline"]) and len(proc["exam"]) == 14
    assert proc["exam"]["linearity"] == 1.0 and proc["baseline"]["linearity"] == 1.0     # typed at the end throughout
    assert proc["exam"]["revision_rate"] == 0.0 and proc["exam"]["pause_frac_2s"] == 0.0
    assert r["baseline"]["process"] == proc["baseline"]
    assert not any(f["id"].startswith("process") for f in r["exams"][0]["findings"])      # no flag: scales need study data
