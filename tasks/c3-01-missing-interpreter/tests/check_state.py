"""Per-requirement state checks for hjr/c3-01-missing-interpreter. Reads only the workspace."""

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
    report = _load(ws / "out/report.json")
    ok = isinstance(report, dict)
    readings = ws / "data/readings.csv"
    return {
        "report_valid": ok and set(report) == {"sensors", "anomalies"},
        "sensor_stats": ok and report.get("sensors") == EXPECTED["report"]["sensors"],
        "anomalies": ok and report.get("anomalies") == EXPECTED["report"]["anomalies"],
        "readings_unchanged": readings.is_file()
        and hashlib.sha256(readings.read_bytes()).hexdigest() == EXPECTED["readings_sha256"],
    }
