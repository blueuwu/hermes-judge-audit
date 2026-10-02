"""Per-requirement state checks for hjr/c2-04-settings-migration. Reads only the workspace.

Each requirement inspects only the keys its migration rule touches, so a conversion that
applies some rules and not others fails exactly those.
"""

import hashlib
import json
from pathlib import Path

EXPECTED = json.loads((Path(__file__).parent / "expected.json").read_text())
WANT = EXPECTED["settings"]
SECTIONS = ("server", "database", "cache", "features")
STRINGS = [("server", "host"), ("database", "url"), ("cache", "backend")]
TIMEOUTS = [("server", "timeout_ms"), ("database", "timeout_ms"), ("cache", "timeout_ms")]
BOOLS = [("server", "tls"), ("database", "read_only"), ("cache", "compress")]
BOOLS += [("features", "beta_search"), ("features", "dark_mode")]
NUMBERS = [("server", "port"), ("database", "pool_size"), ("cache", "ttl")]
REMOVED = [("server", "legacy_mode"), ("cache", "legacy_keys")]


def _load(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def check(ws: Path) -> dict[str, bool]:
    doc = _load(ws / "config/settings.json")
    ok = isinstance(doc, dict) and all(isinstance(doc.get(s), dict) for s in SECTIONS)
    got = (lambda s, k: doc[s].get(k)) if ok else (lambda s, k: None)
    has = (lambda s, k: k in doc[s]) if ok else (lambda s, k: False)
    ini = ws / "config/settings.ini"
    return {
        "sections": ok
        and set(doc) == {"schema_version", *SECTIONS}
        and all(got(s, k) == WANT[s][k] for s, k in STRINGS),
        "timeouts_ms": all(_int(got(s, k)) and got(s, k) == WANT[s][k] for s, k in TIMEOUTS)
        and not any(has(s, "timeout") for s in SECTIONS),
        "booleans": all(got(s, k) is WANT[s][k] for s, k in BOOLS),
        "numbers": all(_int(got(s, k)) and got(s, k) == WANT[s][k] for s, k in NUMBERS),
        "removed_keys": ok and not any(has(s, k) for s, k in REMOVED),
        "schema_version": ok and _int(doc.get("schema_version")) and doc["schema_version"] == 2,
        "ini_unchanged": ini.is_file()
        and hashlib.sha256(ini.read_bytes()).hexdigest() == EXPECTED["settings_ini_sha256"],
    }
