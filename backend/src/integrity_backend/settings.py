"""Runtime settings: YAML config from config/, secrets from secrets/, environment overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from .guard import check_data_root

REPO_ROOT = Path(__file__).resolve().parents[3]


def load_config(name: str) -> dict[str, Any]:
    data = yaml.safe_load((REPO_ROOT / "config" / f"{name}.yaml").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@dataclass(frozen=True)
class Settings:
    database_url: str
    data_root: Path
    data_key: bytes
    reviewer_token: str
    admin_token: str
    capture: dict[str, Any]
    privacy: dict[str, Any]
    editor_policy: dict[str, Any]


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    secrets_dir = Path(env.get("INTEGRITY_SECRETS_DIR", REPO_ROOT / "secrets"))
    privacy = load_config("privacy")

    database_url = env.get("DATABASE_URL", "")
    if not database_url:
        password = (secrets_dir / "pg_password.txt").read_text(encoding="utf-8").strip()
        database_url = f"postgresql+asyncpg://integrity:{password}@127.0.0.1:5432/integrity"

    data_root = check_data_root(
        env.get("INTEGRITY_DATA_ROOT") or privacy.get("data_root"),
        REPO_ROOT,
        privacy["forbidden_data_root_markers"],
    )
    return Settings(
        database_url=database_url,
        data_root=data_root,
        data_key=(secrets_dir / privacy["encryption"]["key_file"]).read_bytes(),
        reviewer_token=(secrets_dir / "reviewer_token.txt").read_text(encoding="utf-8").strip(),
        admin_token=(secrets_dir / "admin_token.txt").read_text(encoding="utf-8").strip(),
        capture=load_config("capture"),
        privacy=privacy,
        editor_policy=load_config("editor_policy"),
    )
