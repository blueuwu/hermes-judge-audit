"""Check that /app/recover.json has the expected shape. Says nothing about the rows' values."""

import json
import sys
from pathlib import Path

try:
    rows = json.loads(Path(__file__).with_name("recover.json").read_text())
except (OSError, ValueError) as e:
    sys.exit(f"recover.json: {e}")
if not isinstance(rows, list) or not all(
    isinstance(r, dict) and set(r) == {"word", "value"} for r in rows
):
    sys.exit('recover.json must be a list of {"word": ..., "value": ...} objects')
print(f"format ok: {len(rows)} rows")
