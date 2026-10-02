"""Shared helpers for the task verifier tests: load a task's hidden checks and seed workspace."""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from harbor.models.task.config import TaskConfig

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "tasks"
SHARED = ROOT / "harness" / "verifier"
TASK_DIRS = sorted(p for p in TASKS.iterdir() if (p / "task.toml").is_file())


def checker(task: str):
    path = TASKS / task / "tests" / "check_state.py"
    spec = importlib.util.spec_from_file_location(f"check_state_{task.replace('-', '_')}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.check


def config(task_dir: Path) -> TaskConfig:
    return TaskConfig.model_validate(tomllib.loads((task_dir / "task.toml").read_text()))


def workspace(task: str, tmp_path: Path) -> Path:
    ws = tmp_path / "app"
    shutil.copytree(TASKS / task / "environment" / "workspace", ws)
    seed = TASKS / task / "environment" / "seed.sql"
    if seed.is_file():
        (ws / "db").mkdir(exist_ok=True)  # created by the Dockerfile; git keeps no empty dirs
        con = sqlite3.connect(ws / "db" / "app.db")
        con.executescript(seed.read_text())
        con.commit()
        con.close()
    return ws


def solve(task: str, ws: Path, tmp_path: Path) -> None:
    """Run the task's solution/solve.sh against a local workspace in place of /app."""
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash not available")
    shim = tmp_path / "shim"
    shim.mkdir(exist_ok=True)
    # Some hosts (Windows) have no usable python3 on PATH; point it at this interpreter.
    (shim / "python3").write_text(f'#!/bin/sh\nexec "{Path(sys.executable).as_posix()}" "$@"\n')
    (shim / "python3").chmod(0o755)
    script = (TASKS / task / "solution" / "solve.sh").read_text()
    script = re.sub(r"(?<![\w.])/app\b", ws.as_posix(), script)
    shim_dir = _msys(shim) if os.name == "nt" else shim.as_posix()
    subprocess.run([bash, "-c", f'export PATH="{shim_dir}:$PATH"\n{script}'], check=True)


def _msys(path: Path) -> str:
    drive, rest = path.as_posix().split(":", 1)
    return f"/{drive.lower()}{rest}"
