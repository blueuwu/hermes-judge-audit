"""Per-requirement state checks for hjr/s0-01-incident-review. Reads only the workspace."""

import hashlib
import json
from pathlib import Path

EXPECTED = json.loads((Path(__file__).parent / "expected.json").read_text())
SECTIONS = [f"stage_{n}" for n in range(1, 7)] + ["final"]
ORDERED = {"customer_impact_window"}  # [first, last]


def _load(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _norm(v):
    return v.strip().lower() if isinstance(v, str) else v


def _equal(want, got, key: str = "") -> bool:
    if isinstance(want, bool) or isinstance(got, bool):
        return isinstance(want, bool) and isinstance(got, bool) and want == got
    if isinstance(want, (int, float)):
        return isinstance(got, (int, float)) and abs(got - want) < 0.005
    if isinstance(want, str):
        return isinstance(got, str) and _norm(got) == _norm(want)
    if isinstance(want, list):  # lists of strings; only ORDERED keys keep their order
        if not isinstance(got, list) or not all(isinstance(x, str) for x in got):
            return False
        a, b = [_norm(x) for x in want], [_norm(x) for x in got]
        return a == b if key in ORDERED else sorted(a) == sorted(b)
    if isinstance(want, dict):
        if not isinstance(got, dict):
            return False
        got = {_norm(str(k)): v for k, v in got.items()}
        return all(
            _norm(str(k)) in got and _equal(v, got[_norm(str(k))], key=k) for k, v in want.items()
        )
    return want == got


def _evidence_unchanged(ws: Path) -> bool:
    for rel, digest in EXPECTED["evidence_sha256"].items():
        path = ws / rel
        stage_dir = ws / Path(rel).parts[0] / Path(rel).parts[1]
        if not stage_dir.exists():  # not released yet at this boundary
            continue
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            return False
    return True


def check(ws: Path) -> dict[str, bool]:
    report = _load(ws / "report/incident.json")
    report = report if isinstance(report, dict) else {}
    out = {s: _equal(EXPECTED["answers"][s], report.get(s)) for s in SECTIONS}
    out["evidence_unchanged"] = _evidence_unchanged(ws)
    return out
