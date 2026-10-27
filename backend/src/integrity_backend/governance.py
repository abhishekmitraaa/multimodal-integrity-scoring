"""Data-governance values (Q4) and the retention job (SPEC 10.2, 10.3, 10.7).

The values live in config/privacy.yaml (`governance:` and `retention_days_after_project_end`),
entered by the lead from the faculty guide's answers; code never invents them. Until every value is
set, real collection cannot be switched on and the retention job refuses to run. The consent
notice shows them, or a visible "[to be set]" while they are blank.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Mapping, Protocol

REQUIRED = ("data_fiduciary", "contact", "project_end_date",
            "retention_days_after_project_end", "derived_retention_days_after_project_end")
UNSET = "[to be set]"


class GovernanceError(RuntimeError):
    pass


def values(privacy: Mapping[str, Any]) -> dict[str, Any]:
    g = dict(privacy.get("governance") or {})
    g["retention_days_after_project_end"] = privacy.get("retention_days_after_project_end")
    return {k: g.get(k) for k in REQUIRED}


def missing(privacy: Mapping[str, Any]) -> list[str]:
    return [k for k, v in values(privacy).items() if v is None or (isinstance(v, str) and not v.strip())]


def _end_date(v: Any) -> dt.date:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v))


def validate(privacy: Mapping[str, Any]) -> None:
    """Called at startup. Values that are set must be well-formed; real collection needs all of them."""
    v = values(privacy)
    if v["project_end_date"] is not None:
        _end_date(v["project_end_date"])
    for k in ("retention_days_after_project_end", "derived_retention_days_after_project_end"):
        if v[k] is not None and (not isinstance(v[k], int) or isinstance(v[k], bool) or v[k] < 0):
            raise GovernanceError(f"privacy: {k} must be a whole number of days >= 0, got {v[k]!r}")
    if privacy.get("real_collection_enabled") and missing(privacy):
        raise GovernanceError("real_collection_enabled needs every governance value in config/privacy.yaml; "
                              f"missing: {', '.join(missing(privacy))}")


def purge_dates(privacy: Mapping[str, Any]) -> tuple[dt.date, dt.date] | None:
    """(raw logs purge date, derived features purge date), or None while any value is missing."""
    v = values(privacy)
    if v["project_end_date"] is None or v["retention_days_after_project_end"] is None \
            or v["derived_retention_days_after_project_end"] is None:
        return None
    end = _end_date(v["project_end_date"])
    return (end + dt.timedelta(days=v["retention_days_after_project_end"]),
            end + dt.timedelta(days=v["derived_retention_days_after_project_end"]))


def notice_fields(privacy: Mapping[str, Any]) -> dict[str, str]:
    """The governance text the consent notice shows (public, via /api/client-config)."""
    v = values(privacy)
    dates = purge_dates(privacy)
    retention = (f"Raw recordings are deleted {v['retention_days_after_project_end']} days after the project ends "
                 f"(on {dates[0].isoformat()}); pseudonymised derived features "
                 f"{v['derived_retention_days_after_project_end']} days after it (on {dates[1].isoformat()}).") if dates else UNSET
    return {
        "data_fiduciary": str(v["data_fiduciary"]) if v["data_fiduciary"] else UNSET,
        "contact": str(v["contact"]) if v["contact"] else UNSET,
        "retention": retention,
    }


class Erasing(Protocol):
    async def all_pseudonyms(self) -> list[str]: ...
    async def erase_participant(self, pseudonym: str, actor: str) -> tuple[int, int]: ...
    async def log_access(self, actor: str, role: str, action: str, target: str) -> None: ...


async def run_retention(store: Erasing, privacy: Mapping[str, Any], today: dt.date, apply: bool) -> dict[str, Any]:
    """Delete every participant's raw data once the raw-log purge date has passed (SPEC 10.7).

    Dry run unless apply. Each participant goes through the same erasure as a withdrawal (one
    transaction each, tombstone in erasure_log). Derived features live in files under the data
    root, outside the database; their date is reported for the custodian to act on.
    """
    dates = purge_dates(privacy)
    if dates is None:
        raise GovernanceError(f"retention values are not set in config/privacy.yaml; missing: {', '.join(missing(privacy))}")
    raw_date, derived_date = dates
    due = today >= raw_date
    pseudonyms = await store.all_pseudonyms() if due else []
    erased = 0
    if due and apply:
        for p in pseudonyms:
            await store.erase_participant(p, "retention-job")
            erased += 1
        await store.log_access("retention-job", "admin", "retention_purge", f"{erased} participants")
    return {"raw_purge_date": raw_date.isoformat(), "derived_purge_date": derived_date.isoformat(), "due": due,
            "participants": len(pseudonyms), "erased": erased, "applied": apply and due,
            "derived_due": today >= derived_date}
