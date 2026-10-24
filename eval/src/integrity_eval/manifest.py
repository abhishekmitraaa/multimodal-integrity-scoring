"""Run manifest embedded in every report (SPEC 14)."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class RunManifest:
    git_commit: str
    git_dirty: bool
    config_sha256: str
    seed: int
    dataset_ids: tuple[str, ...]
    synthetic: bool

    def as_markdown(self) -> str:
        return " · ".join(f"{k}: `{v}`" for k, v in asdict(self).items())


def config_sha256(repo_root: Path = REPO_ROOT) -> str:
    h = hashlib.sha256()
    for path in sorted((repo_root / "config").glob("*.yaml")):
        h.update(path.name.encode("utf-8") + b"\0" + path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


def _git(*args: str, repo_root: Path) -> str:
    try:
        return subprocess.run(["git", *args], cwd=repo_root, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def run_manifest(seed: int, dataset_ids: tuple[str, ...], synthetic: bool, repo_root: Path = REPO_ROOT) -> RunManifest:
    status = _git("status", "--porcelain", repo_root=repo_root)
    return RunManifest(
        git_commit=_git("rev-parse", "HEAD", repo_root=repo_root),
        git_dirty=status not in ("", "unknown"),
        config_sha256=config_sha256(repo_root),
        seed=seed,
        dataset_ids=dataset_ids,
        synthetic=synthetic,
    )
