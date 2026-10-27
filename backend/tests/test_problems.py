"""Problem files (D-035): practice tasks show code to type; exam tasks never reveal a solution."""

from __future__ import annotations

import ast
from typing import Any

import pytest

from integrity_backend.app import load_problems, public_problem

PROBLEMS = load_problems()
PRACTICE = [p for p in PROBLEMS.values() if p["kind"] == "practice"]
EXAMS = [p for p in PROBLEMS.values() if p["kind"] == "exam"]


@pytest.mark.parametrize("problem", PRACTICE, ids=lambda p: p["id"])
def test_practice_reference_solution_passes_its_own_tests(problem: dict[str, Any]) -> None:
    code = problem["reference_solution"]
    assert code.startswith(problem["starter"].splitlines()[0])   # same function header as the starter
    scope: dict[str, Any] = {}
    exec(code, scope)   # noqa: S102 - our own problem files
    for t in problem["tests"]:
        # eval only runs the call strings in our own problem files, against our own solution
        assert eval(t["call"], scope) == ast.literal_eval(t["expected"]), t   # noqa: S307


@pytest.mark.parametrize("problem", EXAMS, ids=lambda p: p["id"])
def test_exam_problems_carry_no_solution(problem: dict[str, Any]) -> None:
    assert "reference_solution" not in problem


def test_server_never_sends_an_exam_solution_even_if_one_is_added() -> None:
    leaked = {**EXAMS[0], "reference_solution": "def rle(s):\n    return s\n"}
    assert "reference_solution" not in public_problem(leaked)
    assert public_problem(PRACTICE[0])["reference_solution"] == PRACTICE[0]["reference_solution"]


def test_there_are_practice_and_exam_problems() -> None:
    assert PRACTICE and EXAMS


def test_stages_baseline_check_exam() -> None:
    """D-038: practice tasks build the baseline, one check task tests it, the exam is checked against it."""
    stages = sorted(p["stage"] for p in PROBLEMS.values())
    assert stages.count("baseline") == 3 and stages.count("check") == 1 and stages.count("exam") == 6
    assert all(p["kind"] == "practice" for p in PROBLEMS.values() if p["stage"] in ("baseline", "check"))


def test_every_exam_task_is_in_the_study_plan_and_has_frozen_material() -> None:
    """D-046: sitting 2 is the six exam tasks; each has a frozen, provenance-checked LLM solution."""
    from integrity_backend.settings import load_config
    from integrity_backend.study import load_materials

    exams = {pid for pid, p in PROBLEMS.items() if p["kind"] == "exam"}
    assert set(load_config("study")["sitting2_tasks"]) == exams
    assert set(load_materials()) == exams


def test_loader_refuses_a_stage_that_does_not_fit_the_kind(tmp_path: Any, monkeypatch: Any) -> None:
    import integrity_backend.app as app_module

    (tmp_path / "bad.yaml").write_text(
        "id: bad\nkind: exam\nstage: check\ntitle: t\nstatement: s\nstarter: x\ntests: []\n", encoding="utf-8")
    monkeypatch.setattr(app_module, "PROBLEMS_DIR", tmp_path)
    with pytest.raises(ValueError, match="stage must be"):
        app_module.load_problems()
