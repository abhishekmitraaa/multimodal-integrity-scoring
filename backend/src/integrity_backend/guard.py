"""Data-root guard (SPEC 10.6): participant data must live outside the repo and outside cloud sync."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


class DataRootError(RuntimeError):
    pass


def check_data_root(raw: str | Path | None, repo_root: Path, forbidden_markers: Iterable[str]) -> Path:
    """Return the resolved data root, or raise DataRootError explaining why it is unsafe."""
    if raw is None or str(raw).strip() == "":
        raise DataRootError("INTEGRITY_DATA_ROOT is not set; set it to a folder outside the repo and cloud sync")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise DataRootError(f"data root must be an absolute path, got {raw!r}")
    resolved = path.resolve()
    repo = repo_root.resolve()
    if resolved == repo or repo in resolved.parents:
        raise DataRootError(f"data root {resolved} is inside the repository {repo}")
    lowered = str(resolved).lower()
    for marker in forbidden_markers:
        if marker.lower() in lowered:
            raise DataRootError(f"data root {resolved} looks cloud-synced (matches {marker!r})")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved
