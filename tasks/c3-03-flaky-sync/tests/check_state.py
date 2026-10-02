"""Per-requirement state checks for hjr/c3-03-flaky-sync. Reads only the workspace."""

import hashlib
import json
from pathlib import Path

EXPECTED = json.loads((Path(__file__).parent / "expected.json").read_text())


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _load(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def check(ws: Path) -> dict[str, bool]:
    catalog = _load(ws / "catalog.json")
    want = EXPECTED["catalog"]
    ok = isinstance(catalog, dict) and isinstance(catalog.get("items"), list)
    items = {i.get("sku"): i for i in catalog["items"] if isinstance(i, dict)} if ok else {}
    return {
        "prices_synced": _sha(ws / "data/prices.csv") == EXPECTED["fresh_sha256"],
        "active_prices": ok
        and all(items.get(w["sku"]) == w for w in want["items"] if not w["discontinued"]),
        "discontinued_kept": ok
        and all(items.get(w["sku"]) == w for w in want["items"] if w["discontinued"]),
        "as_of_date": ok and catalog.get("synced_as_of") == want["synced_as_of"],
        "apply_script_unchanged": _sha(ws / "bin/apply_prices.py") == EXPECTED["apply_sha256"],
    }
