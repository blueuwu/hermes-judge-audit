"""Per-requirement state checks for hjr/c1-02-access-log-summary. Reads only the workspace."""

import hashlib
import json
from pathlib import Path

EXPECTED = json.loads((Path(__file__).parent / "expected.json").read_text())


def _load(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def check(ws: Path) -> dict[str, bool]:
    summary = _load(ws / "out/summary.json")
    ok = isinstance(summary, dict)
    get = summary.get if ok else (lambda _k: None)
    status = get("status")
    log = ws / "logs/access.log"
    return {
        "summary_valid": ok,
        "request_count": _int(get("requests")) and get("requests") == EXPECTED["requests"],
        "status_counts": isinstance(status, dict) and status == EXPECTED["status"],
        "top_paths": get("top_paths") == EXPECTED["top_paths"],
        "bytes_total": _int(get("bytes")) and get("bytes") == EXPECTED["bytes"],
        "log_unchanged": log.is_file()
        and hashlib.sha256(log.read_bytes()).hexdigest() == EXPECTED["access_log_sha256"],
    }
