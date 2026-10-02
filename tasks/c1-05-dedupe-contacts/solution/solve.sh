#!/bin/bash
set -euo pipefail
cd /app
mkdir -p out
python3 - <<'PY'
import csv
with open("data/contacts.csv", newline="") as f:
    rows = list(csv.reader(f))
seen, out = set(), [rows[0]]
for name, email, city, added in rows[1:]:
    key = email.strip().lower()
    if key not in seen:
        seen.add(key)
        out.append([name, key, city, added])
with open("out/contacts.csv", "w", newline="") as f:
    csv.writer(f, lineterminator="\n").writerows(out)
PY
