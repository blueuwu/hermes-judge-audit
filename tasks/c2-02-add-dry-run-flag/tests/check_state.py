"""Per-requirement state checks for hjr/c2-02-add-dry-run-flag. Reads only the workspace.

The tool and the tests are the workspace's own code, run in subprocesses inside the
network-less verifier container against scratch directories.
"""

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

EXPECTED = json.loads((Path(__file__).parent / "expected.json").read_text())


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _scratch(root: Path) -> Path:
    d = root / "logs"
    d.mkdir()
    for names, age in ((EXPECTED["old"], 20), (EXPECTED["new"], 1)):
        for name in names:
            (d / name).write_text(name)
            t = time.time() - age * 86400
            os.utime(d / name, (t, t))
    (d / "sub").mkdir()
    return d


def _tool(ws: Path, *flags: str) -> tuple[subprocess.CompletedProcess | None, set[str]]:
    with tempfile.TemporaryDirectory() as root:
        d = _scratch(Path(root))
        proc = _run(
            [sys.executable, str(ws / "tools/cleanup.py"), str(d), "--days", "7", *flags], ws
        )
        left = {p.name for p in d.iterdir() if p.is_file()}
    return proc, left


def _lines(proc: subprocess.CompletedProcess | None) -> list[str]:
    return proc.stdout.strip().splitlines() if proc is not None else []


def _usage_section(readme: str) -> str:
    m = re.search(r"^## Usage[ \t]*$(.*?)(?=^## |\Z)", readme, re.M | re.S)
    return m.group(1) if m else ""


def _test_names(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    return [
        n.name
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name.startswith("test")
    ]


def check(ws: Path) -> dict[str, bool]:
    everything = set(EXPECTED["old"]) | set(EXPECTED["new"])
    dry, dry_left = _tool(ws, "--dry-run")
    real, real_left = _tool(ws)
    dry_lines = _lines(dry)
    tests = _run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], ws)
    test_file = ws / "tests/test_cleanup.py"
    source = test_file.read_text() if test_file.is_file() else ""
    names = _test_names(test_file)
    ran = re.search(r"Ran (\d+) test", tests.stderr) if tests is not None else None
    return {
        "dry_run_deletes_nothing": dry is not None
        and dry.returncode == 0
        and dry_left == everything,
        "dry_run_lists_files": dry is not None
        and dry.returncode == 0
        and len(dry_lines) == len(EXPECTED["old"])
        and all(line.startswith("would delete ") for line in dry_lines)
        and sorted(Path(line.removeprefix("would delete ")).name for line in dry_lines)
        == sorted(EXPECTED["old"]),
        "default_unchanged": real is not None
        and real.returncode == 0
        and real_left == set(EXPECTED["new"])
        and sorted(Path(line.removeprefix("deleted ")).name for line in _lines(real))
        == sorted(EXPECTED["old"])
        and all(line.startswith("deleted ") for line in _lines(real)),
        "readme_documents_flag": "--dry-run"
        in _usage_section((ws / "README.md").read_text() if (ws / "README.md").is_file() else ""),
        "test_added": "--dry-run" in source
        and "test_deletes_only_old_files" in names
        and "test_leaves_subdirectories" in names
        and len(names) >= 3,
        "tests_pass": tests is not None
        and tests.returncode == 0
        and ran is not None
        and int(ran.group(1)) == len(names) >= 2,
    }
