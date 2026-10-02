"""Per-requirement state checks for hjr/c2-05-month-end-close. Reads only the workspace."""

import csv
import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

EXPECTED = json.loads((Path(__file__).parent / "expected.json").read_text())


def _hashes(directory: Path) -> dict[str, str]:
    if not directory.is_dir():
        return {}
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in directory.iterdir()
        if p.is_file() and p.suffix == ".csv"
    }


def _summary(path: Path) -> list[list] | None:
    try:
        with path.open(newline="") as f:
            rows = list(csv.reader(f))
        if rows[0] != ["region", "orders", "revenue"]:
            return None
        return [[r[0], int(r[1]), Decimal(r[2])] for r in rows[1:] if r]
    except (OSError, IndexError, ValueError, InvalidOperation, UnicodeDecodeError):
        return None


def check(ws: Path) -> dict[str, bool]:
    sales = _hashes(ws / "sales")
    archived = _hashes(ws / "archive/2026-09")
    want = [[r, n, Decimal(v)] for r, n, v in EXPECTED["summary"]]
    manifest = ws / "archive/2026-09/MANIFEST.txt"
    lines = manifest.read_text().splitlines() if manifest.is_file() else []
    want_manifest = [f"{h}  {n}" for n, h in sorted(EXPECTED["september"].items())]
    return {
        "summary_correct": _summary(ws / "out/2026-09-summary.csv") == want,
        "september_archived": archived == EXPECTED["september"]
        and not set(EXPECTED["september"]) & set(sales),
        "others_untouched": sales == EXPECTED["other"],
        "manifest_correct": [line.rstrip() for line in lines if line.strip()] == want_manifest,
    }
