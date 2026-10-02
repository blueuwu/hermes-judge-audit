"""Per-requirement state checks for hjr/c1-03-rename-config-key. Reads only the workspace."""

import json
from pathlib import Path

EXPECTED = json.loads((Path(__file__).parent / "expected.json").read_text())
FILES = {
    "app": "app.json",
    "db": "db.json",
    "services_payments": "services/payments.json",
    "services_search": "services/search.json",
}


def _load(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def check(ws: Path) -> dict[str, bool]:
    loaded = {req: _load(ws / "config" / name) for req, name in FILES.items()}
    result = {"files_valid": all(v is not None for v in loaded.values())}
    for req, name in FILES.items():
        result[req] = loaded[req] is not None and loaded[req] == EXPECTED[name]
    return result
