#!/bin/bash
set -euo pipefail
cd /app
# The mirror refuses the first attempts with EAGAIN (exit 75); retry until it answers.
for _ in 1 2 3 4 5; do
    if sh bin/sync.sh; then break; fi
done
head -n 1 data/prices.csv | grep -q "2026-10-02"
python3 bin/apply_prices.py
