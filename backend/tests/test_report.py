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
CFG = {"report": RULES, "m": 70, "stride": 35, "clip_s": 1.5, "g_min": 5, "large_insert_chars": 32, "coupling_s": 10.0}


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

    def add(self, etype: str, data: dict[str, Any], t: int | None = None) -> None:
        self.events.append({"type": etype, "t_client_us": self.t if t is None else t, "data": data})

    def type(self, n: int, gap_ms: float, hold_ms: float = 80, jitter: float = 0.3, seed: int = 0) -> "Log":
        rng = np.random.default_rng(seed)
        for i in range(n):
            self.t += int(gap_ms * 1000 * (1 + jitter * rng.uniform(-1, 1)))
            key = {"code": "KeyA" if i % 2 else "KeyS", "cat": "letter", "rep": False, "mods": 0, "target": "editor"}
            self.add("keydown", key)
            self.add("content_change", {"ins_len": 1, "text": "a", "cause": "typed", "flush": False}, self.t + 300)
            self.add("keyup", key, self.t + int(hold_ms * 1000))
        return self

    def paste(self, text: str, after_away_s: float | None = None) -> "Log":
        if after_away_s is not None:
            self.add("blur", {"target": "window"})
            self.t += int(after_away_s * 1e6)
            self.add("focus", {"target": "window"})
        self.t += 2_000_000
        self.add("paste", {"len": len(text)})
        self.add("content_change", {"ins_len": len(text), "text": text, "cause": "paste", "flush": False})
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
