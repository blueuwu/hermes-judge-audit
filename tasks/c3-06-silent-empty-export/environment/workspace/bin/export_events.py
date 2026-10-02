"""Export business events (signups, purchases, refunds) since a date to out/events.csv.

Usage: python3 bin/export_events.py --since YYYY-MM-DD

Reads the events database named by EVENTS_DB (default: the production replica path).
"""

import argparse
import csv
import os
import sqlite3
import sys
from pathlib import Path

BUSINESS = ("signup", "purchase", "refund")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", required=True)
    args = parser.parse_args()
    db = Path(os.environ.get("EVENTS_DB", "/var/lib/events/events.db"))
    rows = []
    if db.is_file():
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = con.execute(
            "SELECT id, ts, kind, user FROM events WHERE ts >= ? AND kind IN (?, ?, ?)"
            " ORDER BY ts, id",
            (args.since, *BUSINESS),
        ).fetchall()
        con.close()
    else:
        print(f"warning: {db} not found; exporting 0 events", file=sys.stderr)
    Path("out").mkdir(exist_ok=True)
    with open("out/events.csv", "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["id", "ts", "kind", "user"])
        w.writerows(rows)
    print(f"exported {len(rows)} events")
    return 0


if __name__ == "__main__":
    sys.exit(main())
