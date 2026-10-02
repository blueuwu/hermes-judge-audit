"""Per-requirement state checks for hjr/c3-05-missing-yaml. Reads only the workspace."""

import hashlib
import json
from pathlib import Path

EXPECTED = json.loads((Path(__file__).parent / "expected.json").read_text())


def _load(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def check(ws: Path) -> dict[str, bool]:
    doc = _load(ws / "out/services.json")
    got = doc.get("services") if isinstance(doc, dict) else None
    ok = isinstance(got, list) and all(isinstance(s, dict) for s in got)
    want = EXPECTED["rendered"]["services"]
    by_name = {s.get("name"): s for s in got} if ok else {}
    src = ws / "config/services.yaml"
    return {
        "services_listed": ok and [s.get("name") for s in got] == [w["name"] for w in want],
        "urls": ok and all(by_name.get(w["name"], {}).get("url") == w["url"] for w in want),
        "replicas": ok
        and all(by_name.get(w["name"], {}).get("replicas") == w["replicas"] for w in want),
        "env_merged": ok and all(by_name.get(w["name"], {}).get("env") == w["env"] for w in want),
        "config_unchanged": src.is_file()
        and hashlib.sha256(src.read_bytes()).hexdigest() == EXPECTED["services_yaml_sha256"],
    }
