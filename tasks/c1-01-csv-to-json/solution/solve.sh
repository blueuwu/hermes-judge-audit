#!/bin/bash
set -euo pipefail
cd /app
mkdir -p out
python3 - <<'PY'
import csv, json
with open("data/orders.csv", newline="") as f:
    rows = [
        {"order_id": int(r["order_id"]), "customer": r["customer"],
         "amount": float(r["amount"]), "shipped": r["shipped"] == "yes"}
        for r in csv.DictReader(f)
    ]
rows.sort(key=lambda r: r["order_id"])
json.dump(rows, open("out/orders.json", "w"), indent=2)
total = round(sum(r["amount"] for r in rows if r["shipped"]), 2)
json.dump({"orders": len(rows), "shipped_amount": total}, open("out/totals.json", "w"))
PY
