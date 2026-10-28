"""Export the study data (D2) for evaluation (D-047): study participants' submitted sessions, with labels.

One JSON line per session: pseudonym, task and stage, the study condition and its onset (seconds on
the client clock), covariates (browser, device answers, timer), and the events. A manifest names the
data set. Real participants give `dataset: d2`; dev testers can be exported only as
`dataset: development` with `not_for_study: true`, which the evaluation refuses unless asked (SPEC 13,
P5). Synthetic participants are never exported. The bundle must be under the data root: outside the
repository and any cloud-synced folder (same rule as the data, D-015).

Onset: the participant-marked time for A1/A4/A5; the session start for scripted sessions and for any
attack session whose start was not marked (recorded as onset_source).

Usage: python -m integrity_eval.d2_export --out D:\\integrity-data\\derived\\d2_2027-03-01 [--include-dev]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import yaml

from .manifest import REPO_ROOT, run_manifest

SCHEMA = 1


def _stages() -> dict[str, str]:
    out = {}
    for path in (REPO_ROOT / "backend" / "problems").glob("*.yaml"):
        p = yaml.safe_load(path.read_text(encoding="utf-8"))
        out[p["id"]] = p["stage"]
    return out


def _device(events: Sequence[dict[str, Any]]) -> dict[str, Any]:
    start = next((e["data"] for e in events if e["type"] == "segment_start"), {})
    device = start.get("device", {}) or {}
    return {"keyboard_type": device.get("keyboard_type"), "os": device.get("os_family"),
            "timer_isolated": (start.get("timer") or {}).get("cross_origin_isolated")}


def to_record(row: dict[str, Any], stages: dict[str, str]) -> dict[str, Any]:
    events = row["events"]
    client = [e for e in events if e.get("t_client_us") is not None]
    first = client[0]["t_client_us"] / 1e6 if client else None
    cond = row["condition"]
    if cond in (None, "genuine", "A7", "A8"):
        onset, source = None, None
    elif row["onset_client_us"] is not None and not row["scripted"]:
        onset, source = row["onset_client_us"] / 1e6, "participant"
    else:
        onset, source = first, "session_start" if row["scripted"] else "session_start (not marked)"
    return {
        "pseudonym": row["pseudonym"], "participant_kind": row["participant_kind"], "session_id": row["session_id"],
        "kind": row["kind"], "stage": stages.get(row["problem_id"]), "problem_id": row["problem_id"],
        "condition": cond if row["kind"] == "exam" else None, "scripted": row["scripted"],
        "onset_s": onset, "onset_source": source,
        "covariates": {"browser": row["browser"]["brand"], "browser_version": row["browser"]["version"], **_device(events)},
        "events": events,
    }


async def _rows(include_dev: bool) -> list[dict[str, Any]]:
    from sqlalchemy.ext.asyncio import create_async_engine

    from integrity_backend.crypto import FieldCipher
    from integrity_backend.settings import load_settings
    from integrity_backend.store import Store

    settings = load_settings()
    engine = create_async_engine(settings.database_url)
    try:
        store = Store(engine, FieldCipher(settings.data_key), {})
        rows = await store.study_export(["real", "dev"] if include_dev else ["real"])
        await store.log_access("admin-cli", "admin", "export_study_data", f"{len(rows)} sessions")
        return rows
    finally:
        await engine.dispose()


def write_bundle(rows: Sequence[dict[str, Any]], out: Path, include_dev: bool, seed: int) -> dict[str, Any]:
    from integrity_backend.guard import check_data_root
    from integrity_backend.settings import load_config

    if out.exists() and any(out.iterdir()):          # never overwrites or mixes into an earlier bundle
        raise FileExistsError(f"{out} already exists and is not empty")
    out = check_data_root(out, REPO_ROOT, load_config("privacy")["forbidden_data_root_markers"])
    out.mkdir(parents=True, exist_ok=True)
    stages = _stages()
    records = [to_record(r, stages) for r in rows]
    development = include_dev and any(r["participant_kind"] == "dev" for r in records)
    with (out / "sessions.jsonl").open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    m = run_manifest(seed, ("d2",), synthetic=False)
    manifest = {
        "schema": SCHEMA, "dataset": "development" if development else "d2", "not_for_study": development,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "participants": len({r["pseudonym"] for r in records}), "sessions": len(records),
        "kinds": sorted({r["participant_kind"] for r in records}), "git_commit": m.git_commit, "config_sha256": m.config_sha256,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export the study data (D2) for evaluation.")
    parser.add_argument("--out", type=Path, required=True, help="a new folder under the data root")
    parser.add_argument("--include-dev", action="store_true", help="also dev testers: the bundle is then labelled development")
    args = parser.parse_args(argv)
    seed = int(yaml.safe_load((REPO_ROOT / "config" / "global.yaml").read_text(encoding="utf-8"))["seed"])
    manifest = write_bundle(asyncio.run(_rows(args.include_dev)), args.out, args.include_dev, seed)
    print(f"wrote {args.out}: {manifest['participants']} participants, {manifest['sessions']} sessions, dataset {manifest['dataset']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
