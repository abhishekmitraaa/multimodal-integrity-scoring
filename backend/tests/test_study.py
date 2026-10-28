"""Study protocol (D-046, SPEC 12.2): plans, sitting rules, materials, onsets, scripted sessions. SYNTHETIC."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from test_api_report import ADMIN, CONSENT, REVIEWER, pasted_exam, submit

from integrity_backend import study
from integrity_backend.settings import load_config

CFG = load_config("study")
FIREFOX = {"browser_brand": "firefox", "browser_version": "135.0", "cross_origin_isolated": True}
EDGE = {**FIREFOX, "browser_brand": "edge"}


def typed(g: Any) -> list[dict[str, Any]]:
    return g.segment_start() + g.type_text("def f(x): return x") + [g.segment_end()]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def study_participant(client: Any) -> dict[str, str]:
    r = client.post("/api/participants", json={"kind": "dev", "age_confirmed": True, "consent": CONSENT, "study": True})
    assert r.status_code == 200
    return r.json()


# ---- the protocol on its own

def test_williams_square_is_latin_and_balanced_for_carry_over() -> None:
    rows = [study.williams_row(6, r) for r in range(6)]
    assert all(sorted(r) == list(range(6)) for r in rows)                                   # each row a permutation
    assert all(sorted(r[c] for r in rows) == list(range(6)) for c in range(6))              # each slot sees each condition
    pairs = [(r[i], r[i + 1]) for r in rows for i in range(5)]
    assert len(set(pairs)) == len(pairs) == 30                                              # each ordered pair once
    plans = [study.plan(r, CFG) for r in range(6)]
    assert all([c for _, _, c in p].count("genuine") == 2 for p in plans)
    for task in CFG["sitting2_tasks"]:                                                      # every task meets every condition
        assert {c for p in plans for _, t, c in p if t == task} == set(CFG["conditions"])


def test_materials_refuse_edits(tmp_path: Path) -> None:
    src = next(study.MATERIALS_DIR.glob("*.yaml")).read_text(encoding="utf-8")
    (tmp_path / "x.yaml").write_text(src.replace("    return", "    return  ", 1), encoding="utf-8")
    with pytest.raises(ValueError, match="sha256"):
        study.load_materials(tmp_path)
    (tmp_path / "x.yaml").write_text(src.replace("llm_generated", "handwritten"), encoding="utf-8")
    with pytest.raises(ValueError, match="llm_generated"):
        study.load_materials(tmp_path)


def test_sitting_rules() -> None:
    now = datetime(2026, 11, 2, 10, tzinfo=timezone.utc)
    ok = dict(session_kind="practice", participant_kind="real", first_practice=None, now=now, cfg=CFG)
    study.check_session_env(env=FIREFOX, **ok)
    for env, msg in ((None, "browser details"), ({**FIREFOX, "browser_brand": "safari"}, "Chrome, Edge or Firefox"),
                     ({**FIREFOX, "cross_origin_isolated": False}, "isolated")):
        with pytest.raises(study.StudyRuleError, match=msg):
            study.check_session_env(env=env, **ok)
    exam = dict(session_kind="exam", env=FIREFOX, now=now, cfg=CFG)
    with pytest.raises(study.StudyRuleError, match="practice tasks"):
        study.check_session_env(participant_kind="real", first_practice=None, **exam)
    with pytest.raises(study.StudyRuleError, match="same browser"):
        study.check_session_env(participant_kind="real", first_practice=("edge", now - timedelta(days=2)), **exam)
    with pytest.raises(study.StudyRuleError, match="sitting 2 opens"):
        study.check_session_env(participant_kind="real", first_practice=("firefox", now - timedelta(hours=3)), **exam)
    study.check_session_env(participant_kind="real", first_practice=("firefox", now - timedelta(hours=21)), **exam)
    study.check_session_env(participant_kind="dev", first_practice=("firefox", now - timedelta(minutes=5)), **exam)


# ---- over the API

def test_plan_conditions_materials_and_onset(client: Any, db_url: str) -> None:
    p, q = study_participant(client), study_participant(client)
    me = bearer(p["participant_token"])
    plan = client.get("/api/me/plan", headers=me).json()
    assert plan["study"] is True and plan["sitting2_opens_at"] is None                    # dev: no sitting gap
    assert [s["problem_id"] for s in plan["slots"]] == CFG["sitting2_tasks"]
    other = client.get("/api/me/plan", headers=bearer(q["participant_token"])).json()
    assert [s["condition"] for s in plan["slots"]] != [s["condition"] for s in other["slots"]]   # next Latin-square row

    r = client.post("/api/sessions", json={"participant_token": p["participant_token"], "kind": "practice", "problem_id": "practice_sum_evens"})
    assert r.status_code == 409 and "browser details" in r.text
    submit(client, p["participant_token"], "practice", "practice_sum_evens", typed, env=FIREFOX)
    r = client.post("/api/sessions", json={"participant_token": p["participant_token"], "kind": "exam",
                                           "problem_id": CFG["sitting2_tasks"][0], "env": EDGE})
    assert r.status_code == 409 and "same browser" in r.text

    slots = {s["condition"]: s for s in plan["slots"]}
    genuine = next(s for s in plan["slots"] if s["condition"] == "genuine")
    a1 = slots["A1"]
    g_sid = submit(client, p["participant_token"], "exam", genuine["problem_id"], pasted_exam, env=FIREFOX)
    r = client.post("/api/sessions", json={"participant_token": p["participant_token"], "kind": "exam",
                                           "problem_id": a1["problem_id"], "env": FIREFOX})
    a1_sid = r.json()["session_id"]
    assert client.post("/api/sessions", json={"participant_token": p["participant_token"], "kind": "exam",
                                              "problem_id": a1["problem_id"], "env": FIREFOX}).status_code == 409   # one per slot

    material = client.get(f"/api/me/material/{a1_sid}", headers=me).json()
    assert material["label"] == "llm_generated" and material["text"].startswith("def ")
    assert client.get(f"/api/me/material/{g_sid}", headers=me).status_code == 404                   # genuine: none
    assert client.get(f"/api/me/material/{a1_sid}", headers=bearer(q["participant_token"])).status_code == 404

    assert client.post("/api/me/onset", json={"session_id": a1_sid, "t_client_us": 5_000_000}, headers=me).status_code == 200
    assert client.post("/api/me/onset", json={"session_id": a1_sid, "t_client_us": 6_000_000}, headers=me).status_code == 409
    assert client.post("/api/me/onset", json={"session_id": g_sid, "t_client_us": 1}, headers=me).status_code == 409

    done = {s["problem_id"]: s for s in client.get("/api/me/plan", headers=me).json()["slots"]}
    assert done[genuine["problem_id"]]["done"] and done[a1["problem_id"]]["session_id"] == a1_sid

    # Reviewers stay blind: no condition anywhere in what they read.
    report = client.get(f"/api/participants/{p['pseudonym']}/report", headers=REVIEWER).json()
    listing = client.get("/api/participants", headers=REVIEWER).json()
    blob = json.dumps([report, listing])
    assert '"condition"' not in blob and "llm_generated" not in blob and "onset" not in blob


def test_non_study_participants_keep_the_simple_flow(client: Any) -> None:
    p = client.post("/api/participants", json={"kind": "dev", "age_confirmed": True, "consent": CONSENT}).json()
    assert client.get("/api/me/plan", headers=bearer(p["participant_token"])).json() == {"study": False, "slots": []}
    submit(client, p["participant_token"], "exam", "exam_run_length", pasted_exam)                    # no env needed


def test_real_participants_wait_a_day_for_sitting_2(make_client: Any) -> None:
    privacy = copy.deepcopy(load_config("privacy"))
    privacy.update(real_collection_enabled=True, retention_days_after_project_end=30,
                   governance={"data_fiduciary": "x", "contact": "y", "project_end_date": "2027-05-31",
                               "derived_retention_days_after_project_end": 30},
                   staff={"shared_reviewer_token": False})
    c = make_client(privacy=privacy)
    p = c.post("/api/participants", json={"kind": "real", "age_confirmed": True, "consent": CONSENT}).json()
    assert p["pseudonym"].startswith("P-")
    plan = c.get("/api/me/plan", headers=bearer(p["participant_token"])).json()
    assert plan["study"] is True                                                                   # real participants always
    submit(c, p["participant_token"], "practice", "practice_sum_evens", typed, env=FIREFOX)
    assert c.get("/api/me/plan", headers=bearer(p["participant_token"])).json()["sitting2_opens_at"] is not None
    r = c.post("/api/sessions", json={"participant_token": p["participant_token"], "kind": "exam",
                                      "problem_id": CFG["sitting2_tasks"][0], "env": FIREFOX})
    assert r.status_code == 409 and "sitting 2 opens" in r.text


def test_scripted_sessions_timing_and_a8_assignment(client: Any, db_url: str) -> None:
    from test_api_reviews import raw

    p = study_participant(client)
    submit(client, p["participant_token"], "practice", "practice_sum_evens", typed, env=FIREFOX)
    timing = client.get(f"/api/admin/participants/{p['pseudonym']}/timing", headers=ADMIN).json()
    assert timing["flights_s"] and timing["holds_s"] and max(timing["flights_s"]) < CFG["a3b"]["flight_max_s"]
    assert client.get(f"/api/admin/participants/{p['pseudonym']}/timing", headers=REVIEWER).status_code == 403

    task = CFG["sitting2_tasks"][2]
    r = client.post("/api/admin/scripted-session", json={"pseudonym": p["pseudonym"], "problem_id": task, "condition": "A3b"},
                    headers=ADMIN)
    assert r.status_code == 200 and r.json()["text"].startswith("def ")
    sid = r.json()["session_id"]
    label = raw(db_url, f"SELECT condition, scripted, onset_at FROM study_labels WHERE session_id = '{sid}'")[0]
    assert label["condition"] == "A3b" and label["scripted"] and label["onset_at"] is not None     # onset = session start
    slot = next(s for s in client.get("/api/me/plan", headers=bearer(p["participant_token"])).json()["slots"] if s["problem_id"] == task)
    assert slot["session_id"] is None                                                               # not the participant's slot

    plan = client.get("/api/me/plan", headers=bearer(p["participant_token"])).json()["slots"]
    g = next(s for s in plan if s["condition"] == "genuine")
    assert client.post(f"/api/admin/participants/{p['pseudonym']}/assign", json={"slot": g["slot"], "condition": "A8"},
                       headers=ADMIN).status_code == 200
    submit(client, p["participant_token"], "exam", g["problem_id"], pasted_exam, env=FIREFOX)
    assert client.post(f"/api/admin/participants/{p['pseudonym']}/assign", json={"slot": g["slot"], "condition": "genuine"},
                       headers=ADMIN).status_code == 409                                            # already started

    client.post("/api/me/withdraw", headers=bearer(p["participant_token"]))
    for table in ("study_assignments", "study_labels"):
        assert raw(db_url, f"SELECT count(*) AS n FROM {table} WHERE {'pseudonym' if table == 'study_assignments' else 'session_id'} = "
                           f"'{p['pseudonym'] if table == 'study_assignments' else sid}'")[0]["n"] == 0


def test_study_export_carries_labels_browser_and_events(client: Any) -> None:
    p = study_participant(client)
    submit(client, p["participant_token"], "practice", "practice_sum_evens", typed, env=FIREFOX)
    slot = client.get("/api/me/plan", headers=bearer(p["participant_token"])).json()["slots"][0]
    sid = submit(client, p["participant_token"], "exam", slot["problem_id"], pasted_exam, env=FIREFOX)
    rows = client.portal.call(client.app.state.store.study_export, ["dev"], [p["pseudonym"]])
    mine = {r["session_id"]: r for r in rows if r["pseudonym"] == p["pseudonym"]}
    assert len(mine) == 2 and mine[sid]["condition"] == slot["condition"] and mine[sid]["browser"]["brand"] == "firefox"
    assert mine[sid]["events"] and all(r["participant_kind"] == "dev" for r in mine.values())
    assert client.portal.call(client.app.state.store.study_export, ["real"], [p["pseudonym"]]) == []   # a dev tester is not D2
