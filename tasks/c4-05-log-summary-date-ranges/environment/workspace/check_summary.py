"""Check that /app/summary.csv has the required layout. Does not check the counts."""

import csv
import sys
from pathlib import Path

PERIODS = ["today", "last_7_days", "last_30_days", "month_to_date", "total"]
SEVERITIES = ["ERROR", "WARNING", "INFO"]

try:
    with Path(__file__).with_name("summary.csv").open(newline="") as f:
        rows = list(csv.reader(f))
except OSError as e:
    sys.exit(f"summary.csv: {e}")
layout = [["period", "severity", "count"]] + [[p, s] for p in PERIODS for s in SEVERITIES]
ok = len(rows) == len(layout) and rows[0] == layout[0]
ok = ok and all(r[:2] == w and len(r) == 3 and r[2].isdigit() for r, w in zip(rows[1:], layout[1:]))
print("layout: " + ("ok" if ok else "FAIL"))
sys.exit(0 if ok else 1)
