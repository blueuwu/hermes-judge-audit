"""Per-requirement state checks for hjr/c3-04-stale-lock. Reads only the workspace."""

import hashlib
import json
from pathlib import Path

EXPECTED = json.loads((Path(__file__).parent / "expected.json").read_text())


def _src_digest(src: Path) -> str | None:
    if not src.is_dir():
        return None
    digest = hashlib.sha256()
    for path in sorted(p for p in src.iterdir() if p.is_file()):
        digest.update(path.name.encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def check(ws: Path) -> dict[str, bool]:
    bundle = ws / "dist/app.bundle.js"
    info = ws / "dist/BUILD_INFO"
    return {
        "bundle_built": bundle.is_file()
        and hashlib.sha256(bundle.read_bytes()).hexdigest() == EXPECTED["bundle_sha256"],
        "build_info": info.is_file() and info.read_text() == EXPECTED["build_info"],
        "lock_released": not (ws / "build.lock").exists(),
        "sources_unchanged": _src_digest(ws / "src") == EXPECTED["src_digest"],
    }
