"""Per-requirement state checks for hjr/c6-04-data-quality-report. Reads only the workspace.

Expected violations are grouped by rule family; each family must be fully reported, and
nothing outside the expected set may be reported.
"""

import json
from pathlib import Path

EXPECTED = json.loads((Path(__file__).parent / "expected.json").read_text())
KEYS = ("table", "row", "column", "rule")
FAMILIES = {
    "nulls_and_duplicates": {"not_null", "unique"},
    "formats": {"email", "date"},
    "enums_and_ranges": {"enum", "range"},
    "foreign_keys": {"foreign_key"},
    "cross_table": {"refund_le_total", "ship_after_order"},
}


def _load(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def check(ws: Path) -> dict[str, bool]:
    report = _load(ws / "out/dq-report.json")
    ok = isinstance(report, list) and all(
        isinstance(v, dict) and set(v) == set(KEYS) for v in report
    )
    got = [tuple(v[k] for k in KEYS) for v in report] if ok else []
    want = [tuple(v[k] for k in KEYS) for v in EXPECTED["violations"]]
    result = {"report_valid": ok and got == sorted(got, key=lambda v: (v[0], v[1], v[2], v[3]))}
    for family, rules in FAMILIES.items():
        result[family] = ok and all(v in got for v in want if v[3] in rules)
    result["no_false_positives"] = ok and len(got) == len(set(got)) and set(got) <= set(want)
    return result
