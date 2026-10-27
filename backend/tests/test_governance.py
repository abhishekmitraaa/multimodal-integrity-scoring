"""Governance values, withdrawal and the retention job (SPEC 10.3, 10.7). SYNTHETIC participants."""

from __future__ import annotations

import copy
import dataclasses
import datetime as dt
from typing import Any

import pytest
from test_api_report import ADMIN, CONSENT, REVIEWER, pasted_exam, submit

from integrity_backend import governance
from integrity_backend.settings import load_config

SET = {"data_fiduciary": "Test project under a test university", "contact": "test-contact@example.invalid",
       "project_end_date": "2027-04-30", "derived_retention_days_after_project_end": 365}


def privacy(**over: Any) -> dict[str, Any]:
    p = copy.deepcopy(load_config("privacy"))
    p["governance"] = {**SET, **over.pop("governance", {})}
    p["retention_days_after_project_end"] = 90
    p.update(over)
    return p


def test_the_repo_config_has_blanks_and_collection_off() -> None:
    p = load_config("privacy")
    assert p["real_collection_enabled"] is False
    assert set(governance.missing(p)) == set(governance.REQUIRED)          # values are the lead's to enter
    assert governance.notice_fields(p) == {"data_fiduciary": "[to be set]", "contact": "[to be set]", "retention": "[to be set]"}
    governance.validate(p)


def test_real_collection_needs_every_value() -> None:
    named = {"shared_reviewer_token": False}                            # D-044: real collection needs named accounts
    governance.validate(privacy(real_collection_enabled=True, staff=named))
    with pytest.raises(governance.GovernanceError, match="contact"):
        governance.validate(privacy(real_collection_enabled=True, staff=named, governance={"contact": None}))
    with pytest.raises(governance.GovernanceError, match="whole number"):
        governance.validate(privacy(governance={"derived_retention_days_after_project_end": -1}))
    with pytest.raises(ValueError):
        governance.validate(privacy(governance={"project_end_date": "end of term"}))


def test_purge_dates_and_notice_text() -> None:
    p = privacy()
    assert governance.purge_dates(p) == (dt.date(2027, 7, 29), dt.date(2028, 4, 29))
    text = governance.notice_fields(p)["retention"]
    assert "90 days" in text and "2027-07-29" in text and "365 days" in text


class FakeStore:
    def __init__(self, names: list[str]) -> None:
        self.names, self.erased, self.logged = names, [], []

    async def all_pseudonyms(self) -> list[str]:
        return list(self.names)

    async def erase_participant(self, pseudonym: str, actor: str) -> tuple[int, int]:
        self.erased.append((pseudonym, actor))
        return 1, 1

    async def log_access(self, actor: str, role: str, action: str, target: str) -> None:
        self.logged.append(action)


@pytest.mark.anyio
async def test_retention_job_refuses_waits_dry_runs_then_erases() -> None:
    s = FakeStore(["DEV-A", "SYN-B"])
    with pytest.raises(governance.GovernanceError):
        await governance.run_retention(s, load_config("privacy"), dt.date(2030, 1, 1), apply=True)
    early = await governance.run_retention(s, privacy(), dt.date(2027, 7, 28), apply=True)
    assert not early["due"] and s.erased == []
    dry = await governance.run_retention(s, privacy(), dt.date(2027, 7, 29), apply=False)
    assert dry["due"] and dry["participants"] == 2 and s.erased == []
    done = await governance.run_retention(s, privacy(), dt.date(2027, 7, 29), apply=True)
    assert done["erased"] == 2 and s.erased == [("DEV-A", "retention-job"), ("SYN-B", "retention-job")]
    assert s.logged == ["retention_purge"] and not done["derived_due"]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_app_refuses_to_start_collecting_without_governance(settings: Any) -> None:
    from integrity_backend.app import create_app

    p = privacy(real_collection_enabled=True, governance={"contact": None})
    with pytest.raises(governance.GovernanceError):
        create_app(dataclasses.replace(settings, privacy=p))


def test_client_config_carries_the_notice_fields(make_client: Any) -> None:
    c = make_client(privacy=privacy())
    notice = c.get("/api/client-config").json()["notice"]
    assert notice["contact"] == SET["contact"] and "2027-07-29" in notice["retention"]


def test_withdrawal_erases_everything_and_the_token_stops_working(client: Any, db_url: str) -> None:
    from test_api_reviews import raw

    p = client.post("/api/participants", json={"kind": "synthetic", "age_confirmed": True, "consent": CONSENT}).json()
    auth = {"Authorization": f"Bearer {p['participant_token']}"}
    exam = submit(client, p["participant_token"], "exam", "exam_run_length", pasted_exam)
    client.post("/api/me/appeals", json={"session_id": exam, "note": "Please read my explanation."}, headers=auth)
    client.post(f"/api/sessions/{exam}/decision", json={"decision": "inconclusive", "notes": "Asked the student."}, headers=REVIEWER)

    assert client.post("/api/me/withdraw").status_code == 401
    r = client.post("/api/me/withdraw", headers=auth)
    assert r.status_code == 200 and r.json()["n_sessions"] == 1
    assert client.get("/api/me/report", headers=auth).status_code == 403
    assert client.post("/api/me/withdraw", headers=auth).status_code == 403
    assert client.get(f"/api/participants/{p['pseudonym']}/report", headers=REVIEWER).status_code == 404
    for table in ("sessions", "events", "review_decisions", "appeals"):
        assert raw(db_url, f"SELECT count(*) AS n FROM {table} WHERE session_id = '{exam}'")[0]["n"] == 0
    log = client.get("/api/access-log", headers=ADMIN).json()
    assert any(e["action"] == "withdraw_and_erase" for e in log)
    # Earlier entries naming the participant or their exam are redacted, not left behind (migration 0003).
    assert not any(x in (e["target"], e["actor"]) for e in log for x in (p["pseudonym"], exam))
    redacted = {(e["action"], e["actor"], e["target"]) for e in log if "[erased]" in (e["actor"], e["target"])}
    assert ("add_appeal", "[erased]", "[erased]") in redacted
    assert ("record_decision:inconclusive", "reviewer-1", "[erased]") in redacted


def test_access_log_redaction_is_the_only_update_allowed(client: Any, db_url: str) -> None:
    import asyncio

    import asyncpg

    client.get("/api/participants", headers=REVIEWER)

    async def attempt(sql: str, erasure: bool) -> None:
        conn = await asyncpg.connect(db_url.replace("postgresql+asyncpg://", "postgresql://"))
        try:
            async with conn.transaction():
                if erasure:
                    await conn.execute("SELECT set_config('integrity.erasure', 'on', true)")
                await conn.execute(sql)
        finally:
            await conn.close()

    with pytest.raises(Exception, match="append-only"):
        asyncio.run(attempt("UPDATE access_log SET target = '[erased]'", erasure=False))      # not outside erasure
    with pytest.raises(Exception, match="append-only"):
        asyncio.run(attempt("UPDATE access_log SET action = 'nothing'", erasure=True))        # never anything else
    with pytest.raises(Exception, match="append-only"):
        asyncio.run(attempt("UPDATE access_log SET target = 'someone-else'", erasure=True))   # only to '[erased]'
    with pytest.raises(Exception, match="append-only"):
        asyncio.run(attempt("DELETE FROM access_log", erasure=True))
    asyncio.run(attempt("UPDATE access_log SET actor = '[erased]' WHERE id = (SELECT max(id) FROM access_log)", erasure=True))


def test_retention_job_against_the_database(make_client: Any) -> None:
    c = make_client(privacy=privacy())
    names = {c.post("/api/participants", json={"kind": "synthetic", "age_confirmed": True, "consent": CONSENT}).json()["pseudonym"]
             for _ in range(2)}
    store = c.app.state.store
    assert names <= set(c.portal.call(store.all_pseudonyms))
    result = c.portal.call(governance.run_retention, store, privacy(), dt.date(2027, 7, 29), True)
    assert result["erased"] >= 2 and c.portal.call(store.all_pseudonyms) == []


def test_session_ids_are_logged_canonically_and_redacted_in_any_spelling(client: Any) -> None:
    p = client.post("/api/participants", json={"kind": "synthetic", "age_confirmed": True, "consent": CONSENT}).json()
    exam = submit(client, p["participant_token"], "exam", "exam_run_length", pasted_exam)
    odd = "{" + exam.upper().replace("-", "") + "}"           # PostgreSQL accepts this spelling too
    assert client.get(f"/api/sessions/{odd}/verify", headers=REVIEWER).status_code == 200
    log = client.get("/api/access-log", headers=ADMIN).json()
    assert ("verify_chain", exam) in {(e["action"], e["target"]) for e in log}       # canonical form
    client.post("/api/me/withdraw", headers={"Authorization": f"Bearer {p['participant_token']}"})
    log = client.get("/api/access-log", headers=ADMIN).json()
    assert not any(exam.replace("-", "") in e["target"].replace("-", "").lower() for e in log)


def test_reads_of_unknown_participants_and_sessions_name_nobody(client: Any) -> None:
    assert client.get("/api/participants/SYN-NOSUCH00/report", headers=REVIEWER).status_code == 404
    assert client.get("/api/sessions/00000000-0000-0000-0000-000000000000/replay", headers=REVIEWER).status_code == 404
    assert client.get("/api/sessions/not-a-uuid/events", headers=REVIEWER).status_code == 404
    targets = {e["target"] for e in client.get("/api/access-log", headers=ADMIN).json()}
    assert {"[unknown participant]", "[unknown session]"} <= targets
    assert not targets & {"SYN-NOSUCH00", "not-a-uuid", "00000000-0000-0000-0000-000000000000"}
