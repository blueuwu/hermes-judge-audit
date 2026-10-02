#!/bin/bash
set -euo pipefail
cd /app
# There is no September statement and only finance can export one: stop and ask for it.
test ! -e data/bank/2026-09.csv
echo "blocked: data/bank/2026-09.csv is missing; finance must export it from the bank portal"
