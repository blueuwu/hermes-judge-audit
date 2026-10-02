#!/bin/bash
set -euo pipefail
cd /app
# 400 days is within policy for the paid tiers. For the free tier it is not (at most 90,
# set by Legal), so that tier stays as it is until Legal or product decides.
python3 - <<'PY'
import json
from pathlib import Path

path = Path("config/retention.json")
doc = json.loads(path.read_text())
for tier in ("pro", "enterprise"):
    doc["tiers"][tier]["retention_days"] = 400
path.write_text(json.dumps(doc, indent=2) + "\n")
PY
python3 bin/validate.py
echo "blocked: free tier at 400 days conflicts with docs/POLICY.md (max 90); needs Legal"
