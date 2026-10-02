"""Check config/retention.json against docs/POLICY.md. Exit 1 on any violation."""

import json
import sys
from pathlib import Path

LIMITS = {"free": 90, "pro": 730, "enterprise": 730}

tiers = json.loads(Path("config/retention.json").read_text())["tiers"]
errors = []
for tier, limit in LIMITS.items():
    days = tiers.get(tier, {}).get("retention_days")
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= limit:
        errors.append(f"{tier}: retention_days must be an integer from 1 to {limit}, got {days!r}")
for e in errors:
    print(e, file=sys.stderr)
print("retention policy: " + ("FAIL" if errors else "ok"))
sys.exit(1 if errors else 0)
