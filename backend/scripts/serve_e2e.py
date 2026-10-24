"""Start the backend for Playwright end-to-end tests against a fresh `integrity_e2e` database.

Only synthetic participants are created by the tests. The database is dropped and recreated on
every start, so nothing from a previous run survives.
Usage: python backend/scripts/serve_e2e.py
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import asyncpg
import uvicorn
from alembic import command
from alembic.config import Config

from integrity_backend.settings import resolve_secrets_dir

REPO = Path(__file__).resolve().parents[2]
DB = "integrity_e2e"


def main() -> None:
    password = (resolve_secrets_dir() / "pg_password.txt").read_text(encoding="utf-8").strip()
    admin_dsn = f"postgresql://integrity:{password}@127.0.0.1:5432/integrity"

    async def reset() -> None:
        conn = await asyncpg.connect(admin_dsn)
        try:
            await conn.execute(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")
            await conn.execute(f"CREATE DATABASE {DB}")
        finally:
            await conn.close()

    asyncio.run(reset())
    url = f"postgresql+asyncpg://integrity:{password}@127.0.0.1:5432/{DB}"
    cfg = Config(str(REPO / "backend" / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    os.environ["DATABASE_URL"] = url
    os.environ.setdefault("INTEGRITY_DATA_ROOT", str(Path(tempfile.gettempdir()) / "integrity-e2e-data"))
    from integrity_backend.app import create_app

    uvicorn.run(create_app(), host="127.0.0.1", port=8000, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
