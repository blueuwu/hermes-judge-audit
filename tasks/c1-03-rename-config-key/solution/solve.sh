#!/bin/bash
set -euo pipefail
cd /app
python3 - <<'PY'
import json
from pathlib import Path


def rename(o):
    if isinstance(o, dict):
        return {("max_retries" if k == "retries" else k): rename(v) for k, v in o.items()}
    if isinstance(o, list):
        return [rename(v) for v in o]
    return o


for path in Path("config").rglob("*.json"):
    path.write_text(json.dumps(rename(json.loads(path.read_text())), indent=2) + "\n")
PY
