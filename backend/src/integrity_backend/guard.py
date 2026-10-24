"""Location guards (SPEC 10.6): participant data and secrets live outside the repo and cloud sync."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


class DataRootError(RuntimeError):
    pass


class SecretsDirError(RuntimeError):
    pass


def _unsafe_reason(path: Path, repo_root: Path, forbidden_markers: Iterable[str]) -> str | None:
    resolved, repo = path.resolve(), repo_root.resolve()
    if resolved == repo or repo in resolved.parents:
        return f"{resolved} is inside the repository {repo}"
    lowered = str(resolved).lower()
    for marker in forbidden_markers:
        if marker.lower() in lowered:
            return f"{resolved} looks cloud-synced (matches {marker!r})"
    return None


def check_data_root(raw: str | Path | None, repo_root: Path, forbidden_markers: Iterable[str]) -> Path:
    """Return the resolved data root, or raise DataRootError explaining why it is unsafe."""
    if raw is None or str(raw).strip() == "":
        raise DataRootError("INTEGRITY_DATA_ROOT is not set; set it to a folder outside the repo and cloud sync")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise DataRootError(f"data root must be an absolute path, got {raw!r}")
    reason = _unsafe_reason(path, repo_root, forbidden_markers)
    if reason:
        raise DataRootError(f"data root {reason}")
    resolved = path.resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def check_secrets_dir(path: Path, repo_root: Path, forbidden_markers: Iterable[str]) -> Path:
    """Return the resolved secrets folder, or raise SecretsDirError (D-028). Never creates it."""
    if not path.is_absolute():
        raise SecretsDirError(f"secrets folder must be an absolute path, got {str(path)!r}")
    reason = _unsafe_reason(path, repo_root, forbidden_markers)
    if reason:
        raise SecretsDirError(f"secrets folder {reason}; move it and set INTEGRITY_SECRETS_DIR")
    return path.resolve()
