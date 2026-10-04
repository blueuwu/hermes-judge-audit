"""Per-requirement state checks for hjr/c2-01-rename-function. Reads only the workspace.

Behavioural checks run the workspace's own code in a subprocess, inside the network-less
verifier container.

v2: callers_updated reads call sites (the code's names, not text) in the modules that use the
function and in the task's original tests, so a new test of the deprecated alias is allowed;
docs_updated asks that compute_total is documented and that calc_total appears in API.md only
in a section on the deprecated alias; tests_pass asks for success and at least the original
number of tests.
"""

import ast
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


def _names(node: ast.AST) -> set[str]:
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, ast.ImportFrom | ast.Import):
            out |= {a.name for a in n.names}
    return out


def _tree(path: Path) -> ast.Module | None:
    try:
        return ast.parse(_read(path))
    except SyntaxError:
        return None


def _callers_updated(ws: Path) -> bool:
    modules = [_tree(ws / p) for p in EXPECTED["caller_modules"]]
    if any(t is None or "calc_total" in _names(t) for t in modules):
        return False
    tests = _tree(ws / "tests/test_totals.py")
    if tests is None:
        return False
    original = {
        n.name: n
        for n in ast.walk(tests)
        if isinstance(n, ast.FunctionDef) and n.name in EXPECTED["original_tests"]
    }
    return sorted(original) == sorted(EXPECTED["original_tests"]) and not any(
        "calc_total" in _names(n) for n in original.values()
    )


def _sections(md: str) -> list[tuple[str, str]]:
    parts = re.split(r"^## (.*)$", md, flags=re.M)
    return list(zip(parts[1::2], parts[2::2], strict=True))


def _docs_updated(api: str) -> bool:
    sections = _sections(api)
    documented = any("billing.totals.compute_total(" in h for h, _ in sections)
    alias_only = all(
        "calc_total" in h and "deprecat" in body.lower()
        for h, body in sections
        if "calc_total" in h + body
    )
    preamble = re.split(r"^## ", api, maxsplit=1, flags=re.M)[0]
    return documented and alias_only and "calc_total" not in preamble


def _ran(stderr: str) -> int:
    m = re.search(r"^Ran (\d+) tests? in ", stderr, re.M)
    return int(m.group(1)) if m else 0


def check(ws: Path) -> dict[str, bool]:
    cases = EXPECTED["cases"]
    want = [c["total"] for c in cases]
    probe = _json(_run(ws, "-c", PROBE, json.dumps(cases)))
    tests = _run(ws, "-m", "unittest", "discover", "-s", "tests")
    api = _read(ws / "docs/API.md")
    return {
        "renamed_definition": re.search(
            r"^def compute_total\(", _read(ws / "billing/totals.py"), re.M
        )
        is not None
        and probe is not None
        and probe["new"] == want,
        "callers_updated": _callers_updated(ws) and _json(_run(ws, "-c", CLI)) == 1,
        "deprecated_alias": probe is not None and probe["old"] == want and probe["warned"],
        "docs_updated": _docs_updated(api),
        "changelog_entry": "compute_total" in _unreleased(_read(ws / "CHANGELOG.md")),
        "tests_pass": tests is not None
        and tests.returncode == 0
        and _ran(tests.stderr) >= EXPECTED["original_test_count"],
    }
