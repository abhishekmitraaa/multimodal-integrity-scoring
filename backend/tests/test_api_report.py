"""Report endpoints (D-036) over the real ingest path against PostgreSQL. SYNTHETIC traffic.

The test settings use an empty data root, so no keystroke model is installed: the keystroke check
must say "unavailable" and the clipboard evidence must still work.
"""

from __future__ import annotations

import json
from typing import Any

from synthetic_events import SyntheticTyping, batch

REVIEWER = {"Authorization": "Bearer reviewer-test-token"}
ADMIN = {"Authorization": "Bearer admin-test-token"}
CONSENT = {"notice_version": "draft-p1", "notice_sha256": "a" * 64, "choices": {"participation": True}}


def submit(client: Any, participant_token: str, kind: str, problem: str, events_of: Any) -> str:
    r = client.post("/api/sessions", json={"participant_token": participant_token, "kind": kind, "problem_id": problem})
    assert r.status_code == 200, r.text
    sid, token = r.json()["session_id"], r.json()["session_token"]
    gen = SyntheticTyping()
    with client.websocket_connect(f"/ws/sessions/{sid}?token={token}") as ws:
        ws.send_text(json.dumps({"type": "hello", "resume": False, "epoch": None}))
        assert ws.receive_json()["type"] == "welcome"
        ws.send_text(json.dumps({"type": "batch", "batch": batch(sid, events_of(gen))}))
        assert ws.receive_json()["type"] == "ack"
        assert client.post(f"/api/sessions/{sid}/close", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    return sid


def pasted_exam(gen: SyntheticTyping) -> list[dict[str, Any]]:
    code = "def rle(s):\n    out = []\n    return ''.join(out)\n" * 2
    events = gen.segment_start("exam_run_length") + gen.type_text("x = 1")
    events += [gen._event("blur", {"target": "window"})]
    gen.t += 30_000_000
    events += [gen._event("focus", {"target": "window"})]
    events += [gen.insert(code, cause="paste"),
               gen._event("paste", {"len": len(code), "newlines": code.count("\n"), "trusted": True, "mimes": ["text/plain"],
                                    "start_line": 1, "start_col": 1, "end_line": 7, "end_col": 1})]
    return events + [gen.segment_end()]


def test_participant_list_reports_and_access_log(client: Any) -> None:
    p = client.post("/api/participants", json={"kind": "synthetic", "age_confirmed": True, "consent": CONSENT}).json()
    submit(client, p["participant_token"], "practice", "practice_sum_evens",
           lambda g: g.segment_start() + g.type_text("def sum_evens(xs): return 0") + [g.segment_end()])
    exam = submit(client, p["participant_token"], "exam", "exam_run_length", pasted_exam)

    listed = {x["pseudonym"]: x for x in client.get("/api/participants", headers=REVIEWER).json()}
    assert [s["kind"] for s in listed[p["pseudonym"]]["sessions"]] == ["practice", "exam"]

    report = client.get(f"/api/participants/{p['pseudonym']}/report", headers=REVIEWER).json()
    assert report["model"]["available"] is False
    assert report["baseline"]["status"] == "insufficient"
    [ex] = report["exams"]
    assert ex["session_id"] == exam and ex["state"] == "review"
    flagged = {f["id"] for f in ex["findings"] if f["status"] == "flag"}
    assert {"external_paste", "away_then_paste", "untyped"} <= flagged
    assert next(f for f in ex["findings"] if f["id"] == "keystroke")["status"] == "unavailable"
    assert report["overall"]["state"] == "review" and report["false_flag_note"]

    own = client.get("/api/me/report", headers={"Authorization": f"Bearer {p['participant_token']}"}).json()
    assert own["pseudonym"] == p["pseudonym"] and own["exams"][0]["state"] == "review"

    actions = {(e["action"], e["target"]) for e in client.get("/api/access-log", headers=ADMIN).json()}
    assert ("read_report", p["pseudonym"]) in actions and ("read_own_report", p["pseudonym"]) in actions


def test_report_access_is_refused_without_the_right_token(client: Any) -> None:
    assert client.get("/api/participants", headers={"Authorization": "Bearer nope"}).status_code == 403
    assert client.get("/api/me/report", headers={"Authorization": "Bearer nope"}).status_code == 403
    assert client.get("/api/participants/SYN-NOBODY00/report", headers=REVIEWER).status_code == 404
