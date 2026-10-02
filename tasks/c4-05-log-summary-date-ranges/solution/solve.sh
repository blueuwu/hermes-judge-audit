#!/bin/bash
set -euo pipefail
cd /app
python3 - <<'PY'
import csv
import re
from datetime import date, timedelta
from pathlib import Path

today = date(2025, 8, 12)
periods = {
    "today": today,
    "last_7_days": today - timedelta(days=6),
    "last_30_days": today - timedelta(days=29),
    "month_to_date": today.replace(day=1),
    "total": date.min,
}
severities = ["ERROR", "WARNING", "INFO"]
counts = {(p, s): 0 for p in periods for s in severities}
for path in Path("logs").glob("*.log"):
    day = date.fromisoformat(path.name.split("_", 1)[0])
    found = re.findall(r"\[(ERROR|WARNING|INFO)\]", path.read_text())
    for period, start in periods.items():
        if start <= day <= today:
            for sev in found:
                counts[(period, sev)] += 1
with open("summary.csv", "w", newline="") as f:
    w = csv.writer(f, lineterminator="\n")
    w.writerow(["period", "severity", "count"])
    w.writerows([p, s, counts[(p, s)]] for p in periods for s in severities)
PY
python3 check_summary.py
