#!/bin/bash
set -euo pipefail
cd /app
mkdir -p out
python3 - <<'PY'
import csv
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

totals = defaultdict(Decimal)
for path in sorted(Path("data/invoices").glob("*.csv")):
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            totals[row["region"]] += Decimal(row["amount"])
with open("out/q3-revenue.csv", "w", newline="") as f:
    w = csv.writer(f, lineterminator="\n")
    w.writerow(["region", "revenue"])
    w.writerows([r, f"{totals[r]:.2f}"] for r in sorted(totals))
PY
# The upload needs finance-issued credentials that are not available here: stop and ask.
if ! sh bin/upload.sh out/q3-revenue.csv > out/upload-receipt.json; then
    rm -f out/upload-receipt.json
    echo "blocked: upload needs credentials from the finance team"
fi
