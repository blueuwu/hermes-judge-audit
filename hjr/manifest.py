"""Provenance for a run: code, Hermes and lockfile versions plus input hashes."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from hjr.config import ROOT

HERMES_DIR = ROOT / "third_party" / "hermes-agent"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git(*args: str, cwd: Path = ROOT) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def git_state() -> tuple[str, bool]:
    sha = _git("rev-parse", "HEAD")
    dirty = bool(_git("status", "--porcelain", "--untracked-files=no", "--", ".", ":!results"))
    return sha, dirty


def hermes_sha() -> str:
    return _git("rev-parse", "HEAD", cwd=HERMES_DIR)


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()
