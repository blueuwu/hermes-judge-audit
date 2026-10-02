#!/bin/bash
set -euo pipefail
cd /app
mkdir -p out archive/2026-09
python3 - <<'PY'
import csv
import hashlib
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

orders, revenue = defaultdict(int), defaultdict(Decimal)
for path in sorted(Path("sales").glob("2026-09-*.csv")):
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            orders[row["region"]] += 1
            revenue[row["region"]] += int(row["qty"]) * Decimal(row["unit_price"])
with open("out/2026-09-summary.csv", "w", newline="") as f:
    w = csv.writer(f, lineterminator="\n")
    w.writerow(["region", "orders", "revenue"])
    for region in sorted(orders):
        total = revenue[region].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        w.writerow([region, orders[region], total])

archive = Path("archive/2026-09")
lines = []
for path in sorted(Path("sales").glob("2026-09-*.csv")):
    lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    path.rename(archive / path.name)
(archive / "MANIFEST.txt").write_text("".join(f"{line}\n" for line in lines))
PY
