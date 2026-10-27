"""Named staff accounts (D-044). SYNTHETIC participants."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from test_api_report import ADMIN, CONSENT, REVIEWER, pasted_exam, submit

from integrity_backend import governance
from integrity_backend.settings import load_config


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_a_named_reviewer_signs_decisions_and_can_be_disabled(client: Any) -> None:
    store = client.app.state.store
    token = client.portal.call(store.create_staff_account, "dr-rao", "reviewer")
    assert client.get("/api/staff/me", headers=bearer(token)).json() == {"handle": "dr-rao", "role": "reviewer", "shared": "false"}

    p = client.post("/api/participants", json={"kind": "synthetic", "age_confirmed": True, "consent": CONSENT}).json()
    exam = submit(client, p["participant_token"], "exam", "exam_run_length", pasted_exam)
    r = client.post(f"/api/sessions/{exam}/decision", json={"decision": "dismiss", "notes": "Explained in the viva."}, headers=bearer(token))
    assert r.status_code == 200
    report = client.get(f"/api/participants/{p['pseudonym']}/report", headers=bearer(token)).json()
    assert report["exams"][0]["decisions"][-1]["reviewer"] == "dr-rao"                  # a person, not "reviewer-1"
    log = client.get("/api/access-log", headers=ADMIN).json()
    assert ("dr-rao", "record_decision:dismiss") in {(e["actor"], e["action"]) for e in log}

    assert client.get("/api/access-log", headers=bearer(token)).status_code == 403      # reviewers are not admins
    assert client.portal.call(store.disable_staff_account, "dr-rao") is True
    assert client.get("/api/participants", headers=bearer(token)).status_code == 403     # disabled at once
    assert client.portal.call(store.disable_staff_account, "dr-rao") is False
    assert [a["handle"] for a in client.portal.call(store.list_staff_accounts) if a["disabled_at"]] == ["dr-rao"]


def test_named_admins_and_bad_handles(client: Any) -> None:
    store = client.app.state.store
    admin = client.portal.call(store.create_staff_account, "lead-admin", "admin")
    assert client.get("/api/access-log", headers=bearer(admin)).status_code == 200
    with pytest.raises(ValueError, match="reserved"):
        client.portal.call(store.create_staff_account, "reviewer-1", "reviewer")
    for bad in ("Dr Rao", "x", "1abc"):
        with pytest.raises(Exception):
            client.portal.call(store.create_staff_account, bad, "reviewer")
    with pytest.raises(Exception):
        client.portal.call(store.create_staff_account, "lead-admin", "reviewer")             # handles are unique


def test_the_shared_token_can_be_switched_off(make_client: Any) -> None:
    privacy = copy.deepcopy(load_config("privacy"))
    privacy["staff"] = {"shared_reviewer_token": False}
    c = make_client(privacy=privacy)
    assert c.get("/api/participants", headers=REVIEWER).status_code == 403
    assert c.get("/api/participants", headers=ADMIN).status_code == 200                  # the bootstrap admin token stays


def test_real_collection_requires_named_accounts() -> None:
    p = copy.deepcopy(load_config("privacy"))
    p["governance"] = {"data_fiduciary": "x", "contact": "y", "project_end_date": "2027-04-30",
                       "derived_retention_days_after_project_end": 30}
    p["retention_days_after_project_end"] = 30
    p["real_collection_enabled"] = True
    with pytest.raises(governance.GovernanceError, match="shared_reviewer_token"):
        governance.validate(p)
    p["staff"] = {"shared_reviewer_token": False}
    governance.validate(p)


def test_the_admin_script_adds_lists_and_disables(settings: Any, monkeypatch: Any, capsys: Any) -> None:
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).parents[2] / "scripts" / "staff_accounts.py"
    spec = importlib.util.spec_from_file_location("staff_accounts_cli", path)
    cli = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli, "load_settings", lambda: settings)

    assert cli.main(["add", "dr-cli", "--role", "reviewer"]) == 0
    out = capsys.readouterr().out
    token = out.strip().splitlines()[-1]
    assert "shown once" in out and len(token) >= 40
    assert cli.main(["list"]) == 0 and "dr-cli" in capsys.readouterr().out
    assert cli.main(["add", "admin"]) == 2 and "reserved" in capsys.readouterr().err
    assert cli.main(["disable", "dr-cli"]) == 0
    assert cli.main(["disable", "dr-cli"]) == 1
    assert "DISABLED" in (cli.main(["list"]), capsys.readouterr().out)[1]
