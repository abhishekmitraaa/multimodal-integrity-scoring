"""Study protocol (D-046, SPEC 12.2): sitting-2 plans, frozen study materials and sitting rules.

- Plan: six exam tasks in a fixed order, one condition each, the condition order taken from row r
  of a Williams Latin square (balanced for first-order carry-over), r = the participant's study
  index mod 6. Across rows every condition meets every task and every slot.
- Materials: the frozen LLM solution per exam task (backend/study_materials), served to a study
  participant only inside an A1, A4 or A5 session; the scripted attacks type the same text.
- Sitting rules for study participants: an allowed browser, cross-origin isolated, the same browser
  brand in both sittings, and (for real participants) a gap between sitting 1 and sitting 2. The
  browser facts are client-reported; the rules enforce the protocol, they are not a security control.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

import yaml

CONDITIONS = ("genuine", "A1", "A2", "A3a", "A3b", "A4", "A5", "A7", "A8")
ATTACK_CONDITIONS = frozenset({"A1", "A2", "A3a", "A3b", "A4", "A5"})   # A7 and A8 are genuine work (false-flag tests)
MATERIAL_CONDITIONS = frozenset({"A1", "A4", "A5"})                    # the participant sees the frozen LLM solution
ONSET_CONDITIONS = frozenset({"A1", "A4", "A5"})                       # the participant marks when the role-play starts
MATERIALS_DIR = Path(__file__).resolve().parents[2] / "study_materials"


class StudyRuleError(ValueError):
    """A study-protocol rule refuses this session (the message says which, in plain words)."""


def williams_row(n: int, r: int) -> list[int]:
    """Row r of a Williams design for n (even) treatments: 0, 1, n-1, 2, n-2, ... shifted by r."""
    base, lo, hi = [0], 1, n - 1
    while len(base) < n:
        base.append(lo if len(base) % 2 else hi)
        if len(base) % 2:
            hi -= 1
        else:
            lo += 1
    return [(b + r) % n for b in base]


def plan(row: int, cfg: Mapping[str, Any]) -> list[tuple[int, str, str]]:
    """(slot, problem_id, condition) for the participant on Latin-square row `row`."""
    tasks, conditions = list(cfg["sitting2_tasks"]), list(cfg["conditions"])
    if len(tasks) != len(conditions):
        raise ValueError("study: one condition per sitting-2 task")
    order = williams_row(len(conditions), row % len(conditions))
    return [(slot, tasks[slot], conditions[order[slot]]) for slot in range(len(tasks))]


def load_materials(folder: Path = MATERIALS_DIR) -> dict[str, dict[str, Any]]:
    """Frozen LLM solutions, checked: labelled llm_generated, with model, date, prompt and a matching sha256."""
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(folder.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        m = doc["llm_solution"]
        for key in ("model", "generated_at", "prompt", "text", "sha256"):
            if not m.get(key):
                raise ValueError(f"{path.name}: llm_solution.{key} is required (SPEC 12.2 provenance)")
        if m.get("label") != "llm_generated":
            raise ValueError(f"{path.name}: llm_solution must be labelled llm_generated")
        if hashlib.sha256(m["text"].encode("utf-8")).hexdigest() != m["sha256"]:
            raise ValueError(f"{path.name}: the frozen text no longer matches its sha256; materials must not be edited")
        out[doc["problem_id"]] = m
    return out


def check_session_env(*, session_kind: str, participant_kind: str, env: Mapping[str, Any] | None,
                      first_practice: tuple[str | None, datetime] | None, now: datetime, cfg: Mapping[str, Any]) -> None:
    """Sitting rules for a study participant's new session (SPEC 12.2, D-021, D-025)."""
    if env is None:
        raise StudyRuleError("this study needs the browser details the app sends; reload the page and try again")
    if env.get("browser_brand") not in cfg["allowed_browsers"]:
        raise StudyRuleError("please use Chrome, Edge or Firefox for this study")
    if cfg["require_cross_origin_isolation"] and not env.get("cross_origin_isolated"):
        raise StudyRuleError("this page is not cross-origin isolated; open the study link exactly as given")
    if session_kind != "exam":
        return
    if first_practice is None:
        raise StudyRuleError("do the practice tasks (sitting 1) before the exam tasks")
    brand, started = first_practice
    if brand is not None and env.get("browser_brand") != brand:
        raise StudyRuleError(f"please use the same browser as in sitting 1 ({brand})")
    if participant_kind in cfg["gap_applies_to"]:
        opens = started + timedelta(hours=float(cfg["min_sitting_gap_hours"]))
        if now < opens:
            raise StudyRuleError(f"sitting 2 opens at {opens.isoformat(timespec='minutes')} (at least a day after sitting 1)")
