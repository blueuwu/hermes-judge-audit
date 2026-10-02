"""Per-requirement state checks for hjr/c1-04-fix-slugify. Reads only the workspace.

The visible tests and the hidden cases run the workspace's own code in a subprocess, inside the
network-less verifier container.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

EXPECTED = json.loads((Path(__file__).parent / "expected.json").read_text(encoding="utf-8"))

HIDDEN = """
import json, sys
from textutil import slugify
cases = json.loads(sys.argv[1])
print(json.dumps([slugify(t, **kw) for t, kw, _ in cases]))
"""


def _run(ws: Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            [sys.executable, *args], cwd=ws, capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _hidden(ws: Path) -> bool:
    cases = EXPECTED["hidden_cases"]
    proc = _run(ws, "-c", HIDDEN, json.dumps(cases))
    if proc is None or proc.returncode != 0:
        return False
    try:
        got = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return False
    return got == [want for _, _, want in cases]


def check(ws: Path) -> dict[str, bool]:
    visible = _run(ws, "-m", "unittest", "discover", "-s", "tests")
    test_file = ws / "tests/test_slug.py"
    return {
        "visible_tests_pass": visible is not None
        and visible.returncode == 0
        and "Ran 4 tests" in visible.stderr,
        "hidden_cases": (ws / "textutil/slug.py").is_file() and _hidden(ws),
        "tests_unchanged": test_file.is_file()
        and hashlib.sha256(test_file.read_bytes()).hexdigest() == EXPECTED["test_slug_sha256"],
    }
