"""D2 export and evaluation (D-047): labelled study sessions out of the database, into the harness. SYNTHETIC/dev."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from integrity_eval import fusion_eval as fe
from integrity_eval.d2_eval import BundleError, load_bundle
from integrity_eval.d2_export import to_record, write_bundle
from integrity_eval.fusion_dryrun import StandInEmbedder, _cfg, practice_texts, settings

EVENTS = [{"type": "segment_start", "t_client_us": 1_000_000,
           "data": {"device": {"keyboard_type": "external", "os_family": "windows"}, "timer": {"cross_origin_isolated": True}}},
          {"type": "keydown", "t_client_us": 2_000_000, "data": {"code": "KeyA", "target": "editor"}}]


def row(**over: Any) -> dict[str, Any]:
    base = {"pseudonym": "P-AAAAAAAA", "participant_kind": "real", "session_id": "s1", "kind": "exam",
            "problem_id": "exam_balanced", "created_at": "2027-03-01T10:00:00+00:00", "condition": "A1", "scripted": False,
            "onset_client_us": 5_000_000, "browser": {"brand": "firefox", "version": "135", "cross_origin_isolated": True},
            "events": EVENTS}
    return {**base, **over}


def test_records_carry_condition_onset_and_covariates() -> None:
    stages = {"exam_balanced": "exam", "practice_sum_evens": "baseline"}
    r = to_record(row(), stages)
    assert (r["condition"], r["onset_s"], r["onset_source"], r["stage"]) == ("A1", 5.0, "participant", "exam")
    assert r["covariates"] == {"browser": "firefox", "browser_version": "135", "keyboard_type": "external", "os": "windows",
                               "timer_isolated": True}
    assert to_record(row(scripted=True, condition="A3b", onset_client_us=None), stages)["onset_source"] == "session_start"
    assert to_record(row(onset_client_us=None), stages)["onset_source"] == "session_start (not marked)"
    assert to_record(row(condition="A8"), stages)["onset_s"] is None                       # genuine work: no onset
    assert to_record(row(kind="practice", problem_id="practice_sum_evens", condition=None), stages)["condition"] is None


def test_bundles_are_labelled_and_development_is_refused(tmp_path: Path) -> None:
    real = write_bundle([row()], tmp_path / "real", include_dev=False, seed=1)
    assert real["dataset"] == "d2" and real["not_for_study"] is False
    manifest, sessions = load_bundle(tmp_path / "real", allow_development=False)
    assert manifest["participants"] == 1 and sessions[0].label == "A1" and sessions[0].onset_s == 5.0
    dev = write_bundle([row(participant_kind="dev", pseudonym="DEV-AAAAAAAA")], tmp_path / "dev", include_dev=True, seed=1)
    assert dev["dataset"] == "development" and dev["not_for_study"] is True
    with pytest.raises(BundleError, match="development"):
        load_bundle(tmp_path / "dev", allow_development=False)
    load_bundle(tmp_path / "dev", allow_development=True)
    with pytest.raises(FileExistsError):                                                   # never overwrites a bundle
        write_bundle([row()], tmp_path / "real", include_dev=False, seed=1)


def test_bundle_inside_the_repository_is_refused() -> None:
    from integrity_backend.guard import DataRootError

    with pytest.raises(DataRootError):
        write_bundle([row()], Path(__file__).parent / "d2_bundle_here", include_dev=False, seed=1)


def test_a_bundle_runs_through_the_harness(tmp_path: Path) -> None:
    """Synthetic sessions written as a bundle, read back and evaluated: the path the study data takes."""
    from integrity_eval.synthetic_sessions import generate
    from integrity_eval.fusion_dryrun import EXAM_TEXT

    _, sessions = generate(6, practice_texts(), EXAM_TEXT, _cfg("eval")["fusion_dryrun"], seed=3)
    folder = tmp_path / "bundle"
    folder.mkdir()
    with (folder / "sessions.jsonl").open("w", encoding="utf-8") as f:
        for s in sessions:
            f.write(json.dumps({"pseudonym": s.uid, "kind": s.kind, "stage": "baseline" if s.kind == "practice" else "exam",
                                "problem_id": s.problem_id, "condition": None if s.kind == "practice" else s.label,
                                "onset_s": s.onset_s, "covariates": s.covariates, "events": s.events}) + "\n")
    (folder / "manifest.json").write_text(json.dumps({"dataset": "development", "not_for_study": True, "participants": 6}))
    _, loaded = load_bundle(folder, allow_development=True)
    prep = fe.prepare(loaded, practice_texts(), {"features": _cfg("features"), "scoring": _cfg("scoring"), "models": _cfg("models")})
    out = fe.Harness(prep, StandInEmbedder()).cross_validate(settings(1, 2, 2))
    assert len(out["outcomes"]) == sum(1 for s in loaded if s.kind == "exam")
