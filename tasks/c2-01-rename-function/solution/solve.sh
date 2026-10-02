#!/bin/bash
set -euo pipefail
cd /app
python3 - <<'PY'
from pathlib import Path

for name in ("billing/invoice.py", "billing/cli.py", "tests/test_totals.py", "docs/API.md"):
    path = Path(name)
    path.write_text(path.read_text().replace("calc_total", "compute_total"))

totals = Path("billing/totals.py")
src = totals.read_text().replace("def calc_total(", "def compute_total(")
src = src.replace("from decimal import", "import warnings\nfrom decimal import", 1)
src += """

def calc_total(items: list[dict], tax_rate: str = "0") -> Decimal:
    \"\"\"Deprecated alias of compute_total.\"\"\"
    warnings.warn("calc_total is deprecated; use compute_total", DeprecationWarning, stacklevel=2)
    return compute_total(items, tax_rate)
"""
totals.write_text(src)

changelog = Path("CHANGELOG.md")
changelog.write_text(changelog.read_text().replace(
    "## Unreleased\n",
    "## Unreleased\n\n- Rename `calc_total` to `compute_total`; `calc_total` stays as a deprecated alias.\n",
    1,
))
PY
