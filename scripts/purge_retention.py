"""Retention job (SPEC 10.7): once the raw-log purge date has passed, erase every participant.

The dates come from config/privacy.yaml (project_end_date + retention days, set by the lead from
the faculty guide's answers). It refuses to run while any value is blank. A dry run by default:
it says what would be erased; add --apply to erase. Run it daily (Task Scheduler) or by hand.

Usage:
  python scripts/purge_retention.py            # dry run
  python scripts/purge_retention.py --apply    # erase, if the purge date has passed
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys

from sqlalchemy.ext.asyncio import create_async_engine

from integrity_backend import governance
from integrity_backend.crypto import FieldCipher
from integrity_backend.settings import load_settings
from integrity_backend.store import Store


async def run(apply: bool, today: dt.date) -> dict[str, object]:
    settings = load_settings()
    engine = create_async_engine(settings.database_url)
    try:
        store = Store(engine, FieldCipher(settings.data_key), {})
        return await governance.run_retention(store, settings.privacy, today, apply)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Retention job (SPEC 10.7).")
    parser.add_argument("--apply", action="store_true", help="erase (default: dry run)")
    args = parser.parse_args(argv)
    try:
        r = asyncio.run(run(args.apply, dt.date.today()))
    except governance.GovernanceError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(f"raw-log purge date {r['raw_purge_date']}; derived-feature purge date {r['derived_purge_date']}")
    if not r["due"]:
        print("not due yet: nothing erased")
    elif r["applied"]:
        print(f"erased {r['erased']} participant(s); tombstones are in erasure_log")
    else:
        print(f"due: {r['participants']} participant(s) would be erased. Run again with --apply.")
    if r["derived_due"]:
        print("derived features are due for deletion: delete them from the data root (outside the database) now")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
