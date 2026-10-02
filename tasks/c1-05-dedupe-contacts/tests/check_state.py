"""Per-requirement state checks for hjr/c1-05-dedupe-contacts. Reads only the workspace."""

import csv
import hashlib
import json
from pathlib import Path

EXPECTED = json.loads((Path(__file__).parent / "expected.json").read_text())
HEADER = ["name", "email", "city", "added"]


def _read(path: Path) -> list[list[str]] | None:
    try:
        with path.open(newline="") as f:
            return list(csv.reader(f))
    except (OSError, UnicodeDecodeError, csv.Error):
        return None


def check(ws: Path) -> dict[str, bool]:
    table = _read(ws / "out/contacts.csv")
    ok = bool(table) and all(len(r) == len(HEADER) for r in table[1:])
    rows = table[1:] if ok else []
    keys = [r[1].strip().lower() for r in rows]
    first = {}
    for r in rows:
        first.setdefault(r[1].strip().lower(), r)
    want = EXPECTED["rows"]
    src = ws / "data/contacts.csv"
    return {
        "csv_valid": ok,
        "header": ok and table[0] == HEADER,
        "deduplicated": ok and len(keys) == len(set(keys)) and set(keys) == {w[1] for w in want},
        # the kept row is the first occurrence: its other fields match the original first row
        "kept_first": ok
        and all(w[1] in first and first[w[1]][0::2] == w[0::2] for w in want)
        and all(w[1] in first and first[w[1]][3] == w[3] for w in want),
        "order": ok and keys == [w[1] for w in want],
        "emails_normalised": ok and bool(rows) and all(r[1] == r[1].strip().lower() for r in rows),
        "input_unchanged": src.is_file()
        and hashlib.sha256(src.read_bytes()).hexdigest() == EXPECTED["contacts_csv_sha256"],
    }
