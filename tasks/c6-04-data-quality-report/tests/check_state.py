"""Per-requirement state checks for hjr/c6-04-data-quality-report. Reads only the workspace.

Expected violations are grouped by rule family; each family must be fully reported, and
nothing outside the expected set may be reported.

v2: SCHEMA.md names every rule except uniqueness ("`id` unique"), so a duplicate is graded on
the table, row and column it is reported at, whatever it is called, unless it is called by
another rule's name. data_unchanged (new in v2): the files under data/ are the ones the task
started with, byte for byte ("Do not modify the data").
"""

import hashlib
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

# Rule names SCHEMA.md gives; a report under any other name is read as the unnamed one
NAMED = {"not_null", "email", "date", "enum", "range", "foreign_key"} | FAMILIES["cross_table"]
UNIQUE = {tuple(v[k] for k in KEYS[:3]) for v in EXPECTED["violations"] if v["rule"] == "unique"}


def _rule(v: tuple) -> tuple:
    return v[:3] + ("unique",) if v[3] not in NAMED and v[:3] in UNIQUE else v


def _data_unchanged(ws: Path) -> bool:
    data = ws / "data"
    files = {p.relative_to(data).as_posix(): p for p in data.rglob("*") if p.is_file()}
    want = EXPECTED["data_sha256"]
    return sorted(files) == sorted(want) and all(
        hashlib.sha256(files[rel].read_bytes()).hexdigest() == sha for rel, sha in want.items()
    )


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
    got = [_rule(v) for v in got]
    for family, rules in FAMILIES.items():
        result[family] = ok and all(v in got for v in want if v[3] in rules)
    result["no_false_positives"] = ok and len(got) == len(set(got)) and set(got) <= set(want)
    result["data_unchanged"] = _data_unchanged(ws)
    return result
