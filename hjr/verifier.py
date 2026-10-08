"""Verifier versions, and grading workspaces offline in each task's own verifier image.

A task's verifier is its ``tests/`` directory (the hidden checks, ``grade.py``, the Dockerfile).
``data/verifiers.json`` names a version per task with the sha256 of that directory; a change to
the directory without a version bump fails ``tests/test_mutants.py``.

Grading reuses Phase 1's path: a workspace is packed as a ``bNN.tgz`` snapshot (as the harness
does with ``tar czf -C /app .``) and graded by the task's own ``grade.grade_snapshot`` inside its
verifier image, built from ``tests/`` and run with no network.
"""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from hjr.config import ROOT
from hjr.manifest import hash_order

TASKS = ROOT / "tasks"
VERSIONS = ROOT / "data" / "verifiers.json"
SKIP = {"__pycache__"}
IMAGE_PREFIX = "hjr-verifier"
# Per snapshot; the hidden checks cap each subprocess they start at 30 s.
SECONDS_PER_SNAPSHOT = 120

# Runs inside the verifier image (cwd /tests). Snapshots arrive in a tar on stdin under /in;
# each is graded on its own so one failing check does not lose the rest.
DRIVER = r"""
import json, sys, tarfile, traceback
from pathlib import Path
sys.path.insert(0, "/tests")
from grade import grade_snapshot
with tarfile.open(fileobj=sys.stdin.buffer, mode="r|") as tf:
    tf.extractall("/in", filter="data")
out = []
for p in sorted(Path("/in").glob("b*.tgz")):
    try:
        out.append({"ok": True, **grade_snapshot(p)})
    except Exception:
        out.append({"ok": False, "snapshot": p.name, "error": traceback.format_exc()[-2000:]})
print("HJR-GRADES " + json.dumps(out))
"""


def task_name(task: str) -> str:
    """'hjr/c1-01-csv-to-json' or 'c1-01-csv-to-json' -> 'c1-01-csv-to-json'."""
    return task.split("/", 1)[-1]


def _files(root: Path) -> list[Path]:
    return sorted(
        (p for p in root.rglob("*") if p.is_file() and not set(p.relative_to(root).parts) & SKIP),
        key=hash_order(root),
    )


def tests_sha(task: str, tasks: Path = TASKS) -> str:
    """sha256 over the relative path and bytes of every file in the task's tests/ directory."""
    root = tasks / task_name(task) / "tests"
    h = hashlib.sha256()
    for p in _files(root):
        h.update(p.relative_to(root).as_posix().encode() + b"\0")
        h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def load_versions(path: Path = VERSIONS) -> dict[str, dict[str, str]]:
    return json.loads(path.read_text(encoding="utf-8"))["tasks"]


def version_of(task: str, path: Path = VERSIONS) -> tuple[str, str]:
    """(version, tests sha256) recorded for a task."""
    v = load_versions(path)[task_name(task)]
    return v["version"], v["tests_sha256"]


def tree_sha(root: Path) -> str:
    """sha256 over the relative path and bytes of every file under root (a base workspace)."""
    h = hashlib.sha256()
    for p in sorted((q for q in root.rglob("*") if q.is_file()), key=hash_order(root)):
        h.update(p.relative_to(root).as_posix().encode() + b"\0")
        h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def snapshot_tgz(ws: Path) -> bytes:
    """A workspace packed like the harness's boundary snapshots: members './…', gzip."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        tf.add(ws, arcname=".", filter=_normalise)
    return buf.getvalue()


def _normalise(info: tarfile.TarInfo) -> tarfile.TarInfo:
    # The harness snapshots as root in the agent container; host files carry no useful owner.
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    info.mtime = int(info.mtime)
    return info


def image(task: str, tasks: Path = TASKS) -> str:
    """Build (once) and name the verifier image for the task's current tests/ directory."""
    tag = f"{IMAGE_PREFIX}-{task_name(task)}:{tests_sha(task, tasks)[:12]}"
    have = subprocess.run(["docker", "image", "inspect", tag], capture_output=True)
    if have.returncode != 0:
        subprocess.run(
            ["docker", "build", "-q", "-t", tag, str(tasks / task_name(task) / "tests")],
            check=True,
            capture_output=True,
        )
    return tag


@dataclass(frozen=True)
class Grade:
    ok: bool
    truth_state: str | None = None
    requirements: dict[str, bool] | None = None
    error: str = ""


def grade_snapshots(task: str, snapshots: Sequence[bytes], tasks: Path = TASKS) -> list[Grade]:
    """Grade each snapshot (.tgz bytes) with the task's verifier, in order, in one container."""
    if not snapshots:
        return []
    if len(snapshots) > 99:
        raise ValueError("at most 99 snapshots per call (bNN names)")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for i, data in enumerate(snapshots, start=1):
            info = tarfile.TarInfo(f"b{i:02d}.tgz")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    try:
        tag = image(task, tasks)
        proc = subprocess.run(
            ["docker", "run", "-i", "--rm", "--network", "none", tag, "python3", "-c", DRIVER],
            input=buf.getvalue(),
            capture_output=True,
            timeout=SECONDS_PER_SNAPSHOT * len(snapshots),
        )
    except subprocess.TimeoutExpired:
        return [Grade(False, error="container timed out")] * len(snapshots)
    except subprocess.CalledProcessError as e:
        err = (e.stderr or b"").decode("utf-8", "replace")[-2000:]
        return [Grade(False, error=f"image build failed: {err}")] * len(snapshots)
    lines = [
        ln for ln in proc.stdout.decode("utf-8", "replace").splitlines() if ln.startswith("HJR-")
    ]
    if proc.returncode != 0 or not lines:
        err = proc.stderr.decode("utf-8", "replace")[-2000:]
        return [Grade(False, error=f"exit {proc.returncode}: {err}")] * len(snapshots)
    rows = json.loads(lines[-1].removeprefix("HJR-GRADES "))
    if len(rows) != len(snapshots):
        return [Grade(False, error=f"{len(rows)} grades for {len(snapshots)} snapshots")] * len(
            snapshots
        )
    return [
        Grade(True, r["truth_state"], r["requirements"])
        if r["ok"]
        else Grade(False, error=r["error"])
        for r in rows
    ]
