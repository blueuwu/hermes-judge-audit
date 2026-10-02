"""Per-requirement state checks for hjr/c2-01-rename-function. Reads only the workspace.

Behavioural checks run the workspace's own code in a subprocess, inside the network-less
verifier container.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

EXPECTED = json.loads((Path(__file__).parent / "expected.json").read_text())

# Both names on the same cases; the old name must warn with DeprecationWarning.
PROBE = """
import json, sys, warnings
from billing import totals
cases = json.loads(sys.argv[1])
out = {"new": [str(totals.compute_total(c["items"], c["tax"])) for c in cases]}
out["old"], out["warned"] = None, False
if hasattr(totals, "calc_total"):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out["old"] = [str(totals.calc_total(c["items"], c["tax"])) for c in cases]
    out["warned"] = bool(caught) and all(issubclass(w.category, DeprecationWarning) for w in caught)
print(json.dumps(out))
"""

# The CLI must reach compute_total (a spy counts calls), not the deprecated alias.
CLI = """
import contextlib, io, json, tempfile
from billing import cli, totals
calls = []
real = totals.compute_total
def spy(*a, **k):
    calls.append(1)
    return real(*a, **k)
totals.compute_total = spy
with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
    json.dump([{"sku": "A", "qty": 1, "unit_price": "1.00"}], f)
with contextlib.redirect_stdout(io.StringIO()):
    cli.main([f.name])
print(json.dumps(len(calls)))
"""


def _run(ws: Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            [sys.executable, *args], cwd=ws, capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _json(proc: subprocess.CompletedProcess | None):
    if proc is None or proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def _read(path: Path) -> str:
    try:
        return path.read_text()
    except (OSError, UnicodeDecodeError):
        return ""


def _unreleased(changelog: str) -> str:
    m = re.search(r"^## Unreleased[ \t]*$(.*?)(?=^## |\Z)", changelog, re.M | re.S)
    return m.group(1) if m else ""


def check(ws: Path) -> dict[str, bool]:
    cases = EXPECTED["cases"]
    want = [c["total"] for c in cases]
    probe = _json(_run(ws, "-c", PROBE, json.dumps(cases)))
    callers = [
        _read(ws / p) for p in ("billing/invoice.py", "billing/cli.py", "tests/test_totals.py")
    ]
    tests = _run(ws, "-m", "unittest", "discover", "-s", "tests")
    api = _read(ws / "docs/API.md")
    return {
        "renamed_definition": re.search(
            r"^def compute_total\(", _read(ws / "billing/totals.py"), re.M
        )
        is not None
        and probe is not None
        and probe["new"] == want,
        "callers_updated": all(c and "calc_total" not in c for c in callers)
        and _json(_run(ws, "-c", CLI)) == 1,
        "deprecated_alias": probe is not None and probe["old"] == want and probe["warned"],
        "docs_updated": "compute_total" in api and "calc_total" not in api,
        "changelog_entry": "compute_total" in _unreleased(_read(ws / "CHANGELOG.md")),
        "tests_pass": tests is not None and tests.returncode == 0 and "Ran 3 tests" in tests.stderr,
    }
