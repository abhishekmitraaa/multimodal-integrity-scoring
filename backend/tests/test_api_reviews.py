"""Reviewer decisions and participant appeals (D-039), over the API against PostgreSQL. SYNTHETIC."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from test_api_report import ADMIN, CONSENT, REVIEWER, pasted_exam, submit


def participant(client: Any) -> dict[str, str]:
    return client.post("/api/participants", json={"kind": "synthetic", "age_confirmed": True, "consent": CONSENT}).json()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def raw(db_url: str, sql: str) -> list[Any]:
    import asyncpg

    async def run() -> list[Any]:
        conn = await asyncpg.connect(db_url.replace("postgresql+asyncpg://", "postgresql://"))
        try:
            return list(await conn.fetch(sql))
        finally:
            await conn.close()

    return asyncio.run(run())


def test_decisions_need_notes_a_submitted_exam_and_keep_their_history(client: Any, db_url: str) -> None:
    p = participant(client)
    practice = submit(client, p["participant_token"], "practice", "practice_sum_evens",
                      lambda g: g.segment_start() + g.type_text("def f(): pass") + [g.segment_end()])
    exam = submit(client, p["participant_token"], "exam", "exam_run_length", pasted_exam)

    assert client.post(f"/api/sessions/{exam}/decision", json={"decision": "dismiss", "notes": "short"}, headers=REVIEWER).status_code == 422
    assert client.post(f"/api/sessions/{exam}/decision", json={"decision": "guilty", "notes": "x" * 20}, headers=REVIEWER).status_code == 422
    assert client.post(f"/api/sessions/{practice}/decision", json={"decision": "dismiss", "notes": "Practice is not reviewed."},
                       headers=REVIEWER).status_code == 409
    assert client.post(f"/api/sessions/{exam}/decision", json={"decision": "dismiss", "notes": "x" * 20},
                       headers=bearer(p["participant_token"])).status_code == 403

    first = client.post(f"/api/sessions/{exam}/decision", json={"decision": "inconclusive", "notes": "Paste visible; need to ask."}, headers=REVIEWER)
    assert first.status_code == 200 and first.json()["report_state"] == "review"
    second = client.post(f"/api/sessions/{exam}/decision", json={"decision": "dismiss", "notes": "Student explained the paste: own code."}, headers=REVIEWER)
    assert second.status_code == 200

    report = client.get(f"/api/participants/{p['pseudonym']}/report", headers=REVIEWER).json()
    decisions = report["exams"][0]["decisions"]
    assert [d["decision"] for d in decisions] == ["inconclusive", "dismiss"]          # history kept, last is current
    assert decisions[1]["notes"] == "Student explained the paste: own code." and decisions[1]["reviewer"] == "reviewer-1"
    listed = {x["pseudonym"]: x for x in client.get("/api/participants", headers=REVIEWER).json()}
    assert next(s for s in listed[p["pseudonym"]]["sessions"] if s["session_id"] == exam)["decision"] == "dismiss"

    stored = raw(db_url, "SELECT notes_ct FROM review_decisions")
    assert stored and all(b"explained" not in bytes(r["notes_ct"]) for r in stored)    # encrypted at rest
    with pytest.raises(Exception, match="append-only"):
        raw(db_url, "UPDATE review_decisions SET decision = 'confirm'")
    actions = {e["action"] for e in client.get("/api/access-log", headers=ADMIN).json()}
    assert {"record_decision:inconclusive", "record_decision:dismiss"} <= actions


def test_appeals_only_on_own_submitted_exams_and_participants_see_no_reviewer_details(own_report_client: Any) -> None:
    p, other = participant(own_report_client), participant(own_report_client)
    exam = submit(own_report_client, p["participant_token"], "exam", "exam_run_length", pasted_exam)
    other_exam = submit(own_report_client, other["participant_token"], "exam", "exam_run_length", pasted_exam)
    practice = submit(own_report_client, p["participant_token"], "practice", "practice_sum_evens",
                      lambda g: g.segment_start() + g.type_text("x") + [g.segment_end()])

    note = {"session_id": exam, "note": "I pasted my own helper from my notes file."}
    assert own_report_client.post("/api/me/appeals", json=note).status_code == 401
    assert own_report_client.post("/api/me/appeals", json=note, headers=bearer("not-a-token")).status_code == 403
    assert own_report_client.post("/api/me/appeals", json={**note, "session_id": other_exam}, headers=bearer(p["participant_token"])).status_code == 404
    assert own_report_client.post("/api/me/appeals", json={**note, "session_id": practice}, headers=bearer(p["participant_token"])).status_code == 409
    assert own_report_client.post("/api/me/appeals", json=note, headers=bearer(p["participant_token"])).status_code == 200
    own_report_client.post(f"/api/sessions/{exam}/decision", json={"decision": "dismiss", "notes": "Accepted the explanation."}, headers=REVIEWER)

    own = own_report_client.get("/api/me/report", headers=bearer(p["participant_token"])).json()["exams"][0]
    assert own["appeals"][0]["note"] == note["note"]
    assert own["decisions"] == [{"decision": "dismiss", "at": own["decisions"][0]["at"]}]   # no reviewer, no notes
    staff = own_report_client.get(f"/api/participants/{p['pseudonym']}/report", headers=REVIEWER).json()["exams"][0]
    assert staff["appeals"][0]["note"] == note["note"] and staff["decisions"][0]["notes"] == "Accepted the explanation."


def test_erasure_removes_decisions_and_appeals(own_report_client: Any, db_url: str) -> None:
    p = participant(own_report_client)
    exam = submit(own_report_client, p["participant_token"], "exam", "exam_run_length", pasted_exam)
    own_report_client.post(f"/api/sessions/{exam}/decision", json={"decision": "inconclusive", "notes": "Needs a conversation."}, headers=REVIEWER)
    own_report_client.post("/api/me/appeals", json={"session_id": exam, "note": "Happy to explain my code."}, headers=bearer(p["participant_token"]))
    r = own_report_client.request("DELETE", f"/api/participants/{p['pseudonym']}", headers=ADMIN, json={"request_id": "REQ-1"})
    assert r.status_code == 200, r.text
    assert raw(db_url, f"SELECT count(*) AS n FROM review_decisions WHERE session_id = '{exam}'")[0]["n"] == 0
    assert raw(db_url, f"SELECT count(*) AS n FROM appeals WHERE session_id = '{exam}'")[0]["n"] == 0
