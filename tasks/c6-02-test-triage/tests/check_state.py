"""Per-requirement state checks for hjr/c6-02-test-triage. Reads only the workspace.

The visible suite and hidden cases (one set per bug, taken from the docstrings) run the
workspace's own code in subprocesses inside the network-less verifier container.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

EXPECTED = json.loads((Path(__file__).parent / "expected.json").read_text())

PROBES = {
    "rounding_fixed": """
from decimal import Decimal
from ledgerkit.money import round_cents
cases = {"0.125": "0.13", "-0.125": "-0.13", "1.005": "1.01", "2.665": "2.67", "7.994": "7.99"}
print(all(round_cents(Decimal(k)) == Decimal(v) for k, v in cases.items()))
""",
    "month_end_fixed": """
from datetime import date
from ledgerkit.dates import month_end
cases = [(date(2025, 12, 31), date(2025, 12, 31)), (date(2026, 1, 1), date(2026, 1, 31)),
         (date(2100, 2, 1), date(2100, 2, 28)), (date(2026, 11, 30), date(2026, 11, 30))]
print(all(month_end(d) == want for d, want in cases))
""",
    "parse_fixed": """
from decimal import Decimal
from ledgerkit.parse import parse_amount
ok = all(parse_amount(k) == Decimal(v) for k, v in
         {"(12.00)": "-12.00", "($1,000.25)": "-1000.25", "12,345,678.90": "12345678.90"}.items())
for bad in ("1,2,3", "12.5.0", "", "(5"):
    try:
        parse_amount(bad)
        ok = False
    except ValueError:
        pass
print(ok)
""",
    "fx_fixed": """
from decimal import Decimal
from ledgerkit.fx import convert
rates = {"USD": Decimal("1"), "EUR": Decimal("0.92"), "JPY": Decimal("149.5")}
print(convert(Decimal("1495"), "JPY", "USD", rates) == Decimal("10.00")
      and convert(Decimal("92.00"), "EUR", "JPY", rates) == Decimal("14950.00"))
""",
}


def _run(ws: Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            [sys.executable, *args], cwd=ws, capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _probe(ws: Path, code: str) -> bool:
    proc = _run(ws, "-c", code)
    return proc is not None and proc.returncode == 0 and proc.stdout.strip() == "True"


def _tests_unchanged(ws: Path) -> bool:
    for name, digest in EXPECTED["tests_sha256"].items():
        path = ws / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            return False
    return True


def check(ws: Path) -> dict[str, bool]:
    suite = _run(ws, "-m", "unittest", "discover", "-s", "tests")
    result = {
        "suite_passes": suite is not None
        and suite.returncode == 0
        and f"Ran {EXPECTED['n_tests']} tests" in suite.stderr,
    }
    result |= {name: _probe(ws, code) for name, code in PROBES.items()}
    result["tests_unchanged"] = _tests_unchanged(ws)
    return result
