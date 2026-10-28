"""Webcam video during exam tasks, a demo feature (D-048). SYNTHETIC/dev participants, fake video bytes."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from test_api_report import ADMIN, CONSENT, REVIEWER, pasted_exam, submit

from integrity_backend.settings import load_config
from integrity_backend.video import SIMULATED_LABEL, simulated_head_movement

FAKE = b"\x1a\x45\xdf\xa3 fake-webm-chunk "            # webm magic, then filler: the server never decodes it


def participant(client: Any, video: bool = True, kind: str = "dev") -> dict[str, str]:
    consent = {**CONSENT, "choices": {"participation": True, "video": video}}
    return client.post("/api/participants", json={"kind": kind, "age_confirmed": True, "consent": consent}).json()


def open_exam(client: Any, token: str) -> tuple[str, str]:
    r = client.post("/api/sessions", json={"participant_token": token, "kind": "exam", "problem_id": "exam_run_length"})
    return r.json()["session_id"], r.json()["session_token"]


def upload(client: Any, sid: str, token: str, seq: int, data: bytes = FAKE) -> Any:
    return client.post(f"/api/sessions/{sid}/video?seq={seq}", content=data, headers={"Authorization": f"Bearer {token}"})


def test_chunks_in_order_encrypted_and_admin_only(client: Any, settings: Any) -> None:
    p = participant(client)
    sid, tok = open_exam(client, p["participant_token"])
    assert upload(client, sid, tok, 0, FAKE + b"0").json() == {"chunks": 1}
    assert upload(client, sid, tok, 1, FAKE + b"1").json() == {"chunks": 2}
    assert upload(client, sid, tok, 1, FAKE + b"1").json() == {"chunks": 2}            # a resend is accepted once
    assert upload(client, sid, tok, 3).status_code == 409                               # a gap
    assert upload(client, sid, tok, 2, b"").status_code == 413
    assert upload(client, sid, tok, 2, b"x" * 8_000_001).status_code == 413
    assert upload(client, sid, "wrong-token", 2).status_code == 403

    files = sorted((Path(settings.data_root) / "video" / sid).glob("*.bin"))
    assert len(files) == 2 and all(b"fake-webm" not in f.read_bytes() for f in files)  # encrypted at rest

    r = client.get(f"/api/admin/sessions/{sid}/video", headers=ADMIN)
    assert r.status_code == 200 and r.headers["content-type"] == "video/webm" and r.content == FAKE + b"0" + FAKE + b"1"
    assert client.get(f"/api/admin/sessions/{sid}/video", headers=REVIEWER).status_code == 403
    assert ("view_video", sid) in {(e["action"], e["target"]) for e in client.get("/api/access-log", headers=ADMIN).json()}


def test_video_needs_consent_an_allowed_kind_and_an_open_exam(client: Any, make_client: Any) -> None:
    no = participant(client, video=False)
    sid, tok = open_exam(client, no["participant_token"])
    assert upload(client, sid, tok, 0).status_code == 403                               # did not tick the box
    p = participant(client)
    r = client.post("/api/sessions", json={"participant_token": p["participant_token"], "kind": "practice", "problem_id": "practice_sum_evens"})
    assert upload(client, r.json()["session_id"], r.json()["session_token"], 0).status_code == 403   # exams only
    sid, tok = open_exam(client, p["participant_token"])
    client.post(f"/api/sessions/{sid}/close", headers={"Authorization": f"Bearer {tok}"})
    assert upload(client, sid, tok, 0).status_code == 403                               # submitted: no more video

    privacy = copy.deepcopy(load_config("privacy"))
    privacy["video"]["kinds"] = ["dev"]
    c = make_client(privacy=privacy)
    syn = participant(c, kind="synthetic")
    sid, tok = open_exam(c, syn["participant_token"])
    assert upload(c, sid, tok, 0).status_code == 403                                    # kind not enabled


def test_real_participants_need_explicit_approval_for_video() -> None:
    from integrity_backend import governance

    privacy = copy.deepcopy(load_config("privacy"))
    assert "real" not in privacy["video"]["kinds"] and privacy["video"]["ethics_approved_for_video"] is False
    privacy["video"]["kinds"] = ["dev", "real"]
    with pytest.raises(governance.GovernanceError, match="ethics_approved_for_video"):
        governance.validate(privacy)


def test_reports_show_the_video_and_a_labelled_simulated_panel_to_staff_only(client: Any) -> None:
    p = participant(client)
    sid = submit(client, p["participant_token"], "exam", "exam_run_length", pasted_exam)
    # the session is closed by submit(); add the video through the store, as if it had arrived during the exam
    client.portal.call(client.app.state.store.add_video_chunk, sid, 0, FAKE, 10**9)
    staff = client.get(f"/api/participants/{p['pseudonym']}/report", headers=REVIEWER).json()["exams"][0]
    assert staff["video"]["available"] and staff["video"]["chunks"] == 1
    demo = staff["head_movement_demo"]
    assert demo["simulated"] is True and demo["label"] == SIMULATED_LABEL and demo["samples"]
    assert not any("head" in f["id"] for f in staff["findings"])                        # never a finding
    own = client.get("/api/me/report", headers={"Authorization": f"Bearer {p['participant_token']}"}).json()["exams"][0]
    assert "video" not in own and "head_movement_demo" not in own


def test_withdrawal_deletes_the_video_files(client: Any, settings: Any) -> None:
    p = participant(client)
    sid, tok = open_exam(client, p["participant_token"])
    upload(client, sid, tok, 0)
    folder = Path(settings.data_root) / "video" / sid
    assert folder.exists()
    client.post("/api/me/withdraw", headers={"Authorization": f"Bearer {p['participant_token']}"})
    assert not folder.exists()


def test_simulated_head_movement_is_deterministic_and_bounded() -> None:
    a, b = simulated_head_movement("s-1", 300.0), simulated_head_movement("s-1", 300.0)
    assert a == b and a["simulated"] is True and 0 <= a["facing_screen_share"] <= 1
    assert simulated_head_movement("s-2", 300.0) != a
    long = simulated_head_movement("s-3", 7200.0)
    assert len(long["samples"]) <= 601 and all(x["end"] >= x["start"] for x in long["look_aways"])
