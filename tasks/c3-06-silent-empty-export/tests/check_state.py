"""Per-requirement state checks for hjr/c3-06-silent-empty-export. Reads only the workspace."""

import csv
import json
import sqlite3
from pathlib import Path

EXPECTED = json.loads((Path(__file__).parent / "expected.json").read_text())


def _rows(path: Path) -> list[list[str]] | None:
    try:
        with path.open(newline="") as f:
            return list(csv.reader(f))
    except (OSError, UnicodeDecodeError, csv.Error):
        return None


def _db_count(db: Path) -> int | None:
    if not db.is_file():
        return None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return con.execute("SELECT count(*) FROM events").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error:
        return None


def check(ws: Path) -> dict[str, bool]:
    table = _rows(ws / "out/events.csv")
    body = [r for r in table[1:] if r] if table else []
    want = [[str(c) for c in r] for r in EXPECTED["rows"]]
    return {
        "header": bool(table) and table[0] == ["id", "ts", "kind", "user"],
        "all_events": bool(want) and all(r in body for r in want),
        "only_requested": body == want,
        "db_intact": _db_count(ws / "db/app.db") == EXPECTED["events_total"],
    }
