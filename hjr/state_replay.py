"""Replay adapter for state pairs: reruns recorded tool calls in the task's own image.

Each replay starts a fresh container of the task's environment image (built from
``tasks/<task>/environment``, ``FROM hjr/hermes-base``) with no network, replaces ``/app`` with
the workspace, and sends each recorded call through Hermes's own ``handle_function_call`` at the
audited commit, with the harness's settings (``HERMES_HOME=/tmp/hermes``, ``TERMINAL_ENV=local``,
yolo mode, cwd ``/app``). The result is turned into a ToolEvent exactly as ``goalloop.tool_events``
does (exit code from the result JSON, last 500 characters), and the workspace after the replay
is copied back. Grading uses the frozen verifier through ``verifier.grade_snapshots``.

Windows checkouts lose Unix modes when a snapshot is extracted, so the adapter keeps each
snapshot's member modes (``modes``, set per boundary by the build driver) and restores them
whenever it packs a workspace. A terminal ToolEvent stores only the ``command`` argument, so a
terminal call is replayed with that argument alone. ``pairs.state_pairs`` grades a workspace
before replaying it; the adapter takes the task from that grade, since ``replay`` receives none.
"""

from __future__ import annotations

import base64
import io
import json
import shutil
import subprocess
import tarfile
from collections.abc import Sequence
from pathlib import Path

from hjr import verifier
from hjr.goalloop import TOOL_OUTPUT_TAIL
from hjr.schemas import ToolEvent, VerifierResult

BASE_IMAGE = "hjr/hermes-base:ffc74885"
IMAGE_PREFIX = "hjr-replay"
SECONDS_PER_REPLAY = 300

# Runs inside the task image. Inputs arrive in a tar on stdin under /in.
DRIVER = r"""
import base64, io, json, os, sys, tarfile
sys.path.insert(0, "/opt/hermes")
os.chdir("/app")
from model_tools import handle_function_call

def exit_code(output):
    try:
        parsed = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(parsed, dict):
        for key in ("exit_code", "returncode", "exit"):
            if isinstance(parsed.get(key), int):
                return parsed[key]
    return None

events = json.load(open("/in/events.json", encoding="utf-8"))
out = []
for i, ev in enumerate(events):
    if ev["tool"] == "terminal":
        args = {"command": ev["cmd"]}
    else:
        try:
            args = json.loads(ev["cmd"])
        except json.JSONDecodeError:
            args = {"raw": ev["cmd"]}
    os.chdir("/app")
    result = handle_function_call(ev["tool"], args, task_id="hjr-replay", tool_call_id=f"r{i}")
    text = result if isinstance(result, str) else json.dumps(result)
    out.append({"tool": ev["tool"], "cmd": ev["cmd"], "exit": exit_code(text),
                "out_tail": text[-TAIL:]})
buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode="w:gz") as tf:
    tf.add("/app", arcname=".")
print("HJR-REPLAY " + json.dumps({"events": out,
                                   "workspace": base64.b64encode(buf.getvalue()).decode()}))
""".replace("TAIL", str(TOOL_OUTPUT_TAIL))

SHELL = (
    "mkdir -p /in && tar xf - -C /in && "
    "find /app -mindepth 1 -delete && tar xzf /in/ws.tgz -C /app && "
    "cd /app && /opt/hermes/.venv/bin/python /in/driver.py"
)


class ReplayFailed(RuntimeError):
    pass


def image(task: str, tasks: Path = verifier.TASKS) -> str:
    """Build (once) the task's agent image from its environment directory."""
    env = tasks / verifier.task_name(task) / "environment"
    tag = f"{IMAGE_PREFIX}-{verifier.task_name(task)}:{verifier.tree_sha(env)[:12]}"
    if subprocess.run(["docker", "image", "inspect", tag], capture_output=True).returncode:
        subprocess.run(
            ["docker", "build", "-q", "-t", tag, str(env)], check=True, capture_output=True
        )
    return tag


def snapshot_modes(tgz: bytes) -> dict[str, int]:
    """Unix mode of every member of a snapshot, by path relative to its root."""
    with tarfile.open(fileobj=io.BytesIO(tgz), mode="r:gz") as tf:
        return {m.name.removeprefix("./"): m.mode for m in tf.getmembers()}


def pack(workspace: Path, modes: dict[str, int]) -> bytes:
    """verifier.snapshot_tgz with the snapshot's own modes restored."""

    def restore(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info = verifier._normalise(info)
        name = info.name.removeprefix("./")
        if name in modes:
            info.mode = modes[name]
        return info

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        tf.add(workspace, arcname=".", filter=restore)
    return buf.getvalue()


def extract(tgz: bytes, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(tgz), mode="r:gz") as tf:
        tf.extractall(dest, filter="data")


def _inputs(workspace: Path, events: Sequence[ToolEvent], modes: dict[str, int]) -> bytes:
    buf = io.BytesIO()
    files = {
        "ws.tgz": pack(workspace, modes),
        "events.json": json.dumps([e.model_dump() for e in events]).encode(),
        "driver.py": DRIVER.encode(),
    }
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _restore(workspace: Path, tgz: bytes) -> None:
    for p in workspace.iterdir():
        shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()
    extract(tgz, workspace)


class DockerReplay:
    def __init__(self, tasks: Path = verifier.TASKS) -> None:
        self.tasks = tasks
        self.task: str | None = None
        self.modes: dict[str, int] = {}
        self.failures: list[str] = []
        # Every mutant of a boundary grades and replays the same null copy; identical trees
        # (same task, files and modes) are graded and replayed once.
        self._grades: dict[tuple, VerifierResult] = {}
        self._replays: dict[tuple, tuple[list[ToolEvent], bytes]] = {}

    def _key(self, workspace: Path) -> tuple:
        return self.task, verifier.tree_sha(workspace), json.dumps(self.modes, sort_keys=True)

    def grade(self, task: str, workspace: Path) -> VerifierResult:
        self.task = task
        key = self._key(workspace)
        if key not in self._grades:
            (g,) = verifier.grade_snapshots(task, [pack(workspace, self.modes)], self.tasks)
            if not g.ok:
                raise ReplayFailed(f"grading failed: {g.error[:300]}")
            self._grades[key] = VerifierResult(
                truth_state=g.truth_state, requirements=g.requirements
            )
        return self._grades[key]

    def replay(self, workspace: Path, events: Sequence[ToolEvent]) -> list[ToolEvent]:
        """The replayed events; [] when the replay itself fails, which the builder excludes as
        non-replayable. The failure is kept in ``failures``."""
        try:
            return self._replay(workspace, events)
        except ReplayFailed as exc:
            self.failures.append(str(exc))
            return []

    def _replay(self, workspace: Path, events: Sequence[ToolEvent]) -> list[ToolEvent]:
        if self.task is None:
            raise ReplayFailed("replay before any grade: task unknown")
        key = (*self._key(workspace), json.dumps([e.model_dump() for e in events]))
        if key in self._replays:
            out, tgz = self._replays[key]
            _restore(workspace, tgz)
            return list(out)
        tag = image(self.task, self.tasks)
        cmd = [
            "docker", "run", "-i", "--rm", "--network", "none",
            "-e", "HERMES_HOME=/tmp/hermes", "-e", "TERMINAL_ENV=local",
            "-e", "HERMES_YOLO_MODE=1", tag, "bash", "-c", SHELL,
        ]  # fmt: skip
        try:
            proc = subprocess.run(
                cmd,
                input=_inputs(workspace, events, self.modes),
                capture_output=True,
                timeout=SECONDS_PER_REPLAY,
            )
        except subprocess.TimeoutExpired:
            raise ReplayFailed("replay timed out") from None
        lines = [
            ln
            for ln in proc.stdout.decode("utf-8", "replace").splitlines()
            if ln.startswith("HJR-REPLAY ")
        ]
        if proc.returncode or not lines:
            err = proc.stderr.decode("utf-8", "replace")[-1000:]
            raise ReplayFailed(f"exit {proc.returncode}: {err}")
        result = json.loads(lines[-1].removeprefix("HJR-REPLAY "))
        tgz = base64.b64decode(result["workspace"])
        _restore(workspace, tgz)
        out = [ToolEvent.model_validate(e) for e in result["events"]]
        self._replays[key] = (out, tgz)
        return list(out)


def factory() -> DockerReplay:
    return DockerReplay()


def build(
    boundaries: Sequence,
    cells: Sequence[str],
    workdir: Path,
    jobs: Path | None = None,
    log=print,
):
    """State pairs over dev boundaries, each snapshot extracted from its Phase 1 job."""
    from hjr import regrade
    from hjr.mutants import load_all, require_frozen, retired
    from hjr.pairs import BuildResult, state_pairs

    require_frozen()
    retired_keys = retired()
    mutants = [m for m in load_all().values() if m.key not in retired_keys]
    executor = DockerReplay()
    result = BuildResult()
    for n, b in enumerate(boundaries, 1):
        tgz = regrade.snapshot_path(b.boundary_id, jobs or regrade.JOBS).read_bytes()
        snap = workdir / b.boundary_id.replace("/", "__")
        if not snap.exists():
            extract(tgz, snap)
        executor.modes = snapshot_modes(tgz)
        before = len(executor.failures)
        try:
            part = state_pairs(b, snap, mutants, cells, executor)
        except Exception as exc:
            result.excluded.append(
                {"boundary_id": b.boundary_id, "reason": f"adapter error: {type(exc).__name__}"}
            )
            log(f"[{n}/{len(boundaries)}] {b.boundary_id}: adapter error {exc!s:.300}")
            continue
        result.items.extend(part.items)
        result.excluded.extend(part.excluded)
        for f in executor.failures[before:]:
            log(f"  replay failure: {f[:300]}")
        log(
            f"[{n}/{len(boundaries)}] {b.boundary_id}: {len(part.items)} items, "
            f"{len(part.excluded)} exclusions"
        )
    return result
