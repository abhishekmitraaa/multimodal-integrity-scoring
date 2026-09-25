"""Fixtures for database-backed tests: a throwaway PostgreSQL database per test run."""

from __future__ import annotations

import asyncio
import dataclasses
import os
import uuid
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

REPO = Path(__file__).resolve().parents[2]


def _dsn(db: str) -> str:
    password = (REPO / "secrets" / "pg_password.txt").read_text(encoding="utf-8").strip()
    return f"postgresql://integrity:{password}@127.0.0.1:5432/{db}"


async def _admin(sql: str) -> None:
    import asyncpg

    conn = await asyncpg.connect(_dsn("integrity"), timeout=3)
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def db_url() -> Iterator[str]:
    try:
        asyncio.run(_admin("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - any connection failure means "no database"
        pytest.skip(f"PostgreSQL not reachable ({exc!r}); run: docker compose up -d db")
    name = f"integrity_test_{uuid.uuid4().hex[:8]}"
    asyncio.run(_admin(f"CREATE DATABASE {name}"))
    url = _dsn(name).replace("postgresql://", "postgresql+asyncpg://")

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO / "backend" / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    yield url
    asyncio.run(_admin(f"DROP DATABASE {name} WITH (FORCE)"))


@pytest.fixture
def settings(db_url: str, tmp_path: Path) -> Any:
    from integrity_backend.settings import Settings, load_config

    capture = load_config("capture")
    capture["clock_sync_interval_ms"] = 3_600_000  # no pings unless a test asks for them
    return Settings(
        database_url=db_url,
        data_root=tmp_path,
        data_key=os.urandom(32),
        reviewer_token="reviewer-test-token",
        admin_token="admin-test-token",
        capture=capture,
        privacy=load_config("privacy"),
        editor_policy=load_config("editor_policy"),
    )


@pytest.fixture
def make_client(settings: Any) -> Iterator[Callable[..., Any]]:
    from fastapi.testclient import TestClient

    from integrity_backend.app import create_app

    clients: list[Any] = []

    def factory(**overrides: Any) -> Any:
        s = dataclasses.replace(settings, **overrides) if overrides else settings
        client = TestClient(create_app(s))
        client.__enter__()
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client: Callable[..., Any]) -> Any:
    return make_client()
