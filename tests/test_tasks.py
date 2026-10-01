"""State verifiers for the Harbor tasks, run against hand-built workspaces (no Docker)."""

from __future__ import annotations

import csv
import importlib.util
import json
import shutil
import sqlite3
import tomllib
from pathlib import Path

import pytest
from harbor.models.task.config import TaskConfig

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "tasks"
SHARED = ROOT / "harness" / "verifier"
TASK_DIRS = sorted(p for p in TASKS.iterdir() if (p / "task.toml").is_file())


def _checker(task: str):
    path = TASKS / task / "tests" / "check_state.py"
    spec = importlib.util.spec_from_file_location(f"check_state_{task.replace('-', '_')}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.check


def _config(task_dir: Path) -> TaskConfig:
    return TaskConfig.model_validate(tomllib.loads((task_dir / "task.toml").read_text()))


def _workspace(task: str, tmp_path: Path) -> Path:
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


@pytest.mark.parametrize("task_dir", TASK_DIRS, ids=lambda p: p.name)
def test_task_layout(task_dir: Path):
    cfg = _config(task_dir)
    meta = cfg.metadata
    assert meta["id"] == f"hjr/{task_dir.name}"
    assert cfg.verifier.environment_mode.value == "separate"
    assert "/app" in cfg.artifacts
    for name in ("grade.py", "test.sh", "Dockerfile"):
        assert (task_dir / "tests" / name).read_bytes() == (SHARED / name).read_bytes(), name
    assert (task_dir / "instruction.md").read_text().strip()
    assert (task_dir / "solution" / "solve.sh").is_file()
    # hidden checks never ship in the agent image's build context
    assert not list((task_dir / "environment").rglob("check_state.py"))
    assert not list((task_dir / "environment").rglob("expected.json"))


@pytest.mark.parametrize("task_dir", TASK_DIRS, ids=lambda p: p.name)
def test_seed_workspace_is_not_done_and_names_every_requirement(task_dir: Path, tmp_path):
    result = _checker(task_dir.name)(_workspace(task_dir.name, tmp_path))
    assert list(result) == _config(task_dir).metadata["requirements"]
    assert not all(result.values())


# ---- c1-01-csv-to-json ----------------------------------------------------------------------


def _solve_c1(ws: Path, *, naive_split=False, string_amounts=False):
    lines = (ws / "data/orders.csv").read_text().splitlines()
    if naive_split:
        # split on commas and skip the rows that "look malformed" (the quoted ones)
        header = lines[0].split(",")
        split = [line.split(",") for line in lines[1:]]
        rows = [dict(zip(header, f, strict=True)) for f in split if len(f) == len(header)]
    else:
        rows = list(csv.DictReader(lines))
    out = [
        {
            "order_id": int(r["order_id"]),
            "customer": r["customer"],
            "amount": r["amount"] if string_amounts else float(r["amount"]),
            "shipped": r["shipped"] == "yes",
        }
        for r in rows
    ]
    out.sort(key=lambda r: r["order_id"])
    (ws / "out").mkdir(exist_ok=True)
    (ws / "out/orders.json").write_text(json.dumps(out))
    total = round(sum(float(r["amount"]) for r in out if r["shipped"]), 2)
    (ws / "out/totals.json").write_text(json.dumps({"orders": len(out), "shipped_amount": total}))


def test_c1_reference_solution_is_done(tmp_path):
    ws = _workspace("c1-01-csv-to-json", tmp_path)
    _solve_c1(ws)
    assert all(_checker("c1-01-csv-to-json")(ws).values())


def test_c1_naive_comma_split_breaks_quoted_rows(tmp_path):
    ws = _workspace("c1-01-csv-to-json", tmp_path)
    _solve_c1(ws, naive_split=True)
    result = _checker("c1-01-csv-to-json")(ws)
    assert [k for k, v in result.items() if not v] == ["row_count", "values", "totals"]


def test_c1_string_amounts_fail_types_only(tmp_path):
    ws = _workspace("c1-01-csv-to-json", tmp_path)
    _solve_c1(ws, string_amounts=True)
    result = _checker("c1-01-csv-to-json")(ws)
    assert [k for k, v in result.items() if not v] == ["field_types", "values", "sorted"]


def test_c1_editing_the_input_violates_the_constraint(tmp_path):
    ws = _workspace("c1-01-csv-to-json", tmp_path)
    _solve_c1(ws)
    with (ws / "data/orders.csv").open("a") as f:
        f.write("\n")
    assert not _checker("c1-01-csv-to-json")(ws)["input_unchanged"]


# ---- c3-02-missing-sqlite -------------------------------------------------------------------


def _db(ws: Path) -> sqlite3.Connection:
    return sqlite3.connect(ws / "db/app.db")


def test_c3_reference_solution_is_done(tmp_path):
    ws = _workspace("c3-02-missing-sqlite", tmp_path)
    with _db(ws) as con:
        con.executescript((ws / "migrations/003_add_status.sql").read_text())
    assert all(_checker("c3-02-missing-sqlite")(ws).values())


def test_c3_partial_migration_is_not_done(tmp_path):
    ws = _workspace("c3-02-missing-sqlite", tmp_path)
    with _db(ws) as con:
        con.execute("ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
        con.execute("UPDATE meta SET value = '3' WHERE key = 'schema_version'")
    result = _checker("c3-02-missing-sqlite")(ws)
    assert [k for k, v in result.items() if not v] == ["status_index", "disabled_accounts"]


def test_c3_version_bump_alone_is_not_done(tmp_path):
    ws = _workspace("c3-02-missing-sqlite", tmp_path)
    with _db(ws) as con:
        con.execute("UPDATE meta SET value = '3' WHERE key = 'schema_version'")
    result = _checker("c3-02-missing-sqlite")(ws)
    assert result["schema_version_3"] and not result["status_column"]


def test_c3_rebuilding_users_without_rows_loses_data(tmp_path):
    ws = _workspace("c3-02-missing-sqlite", tmp_path)
    with _db(ws) as con:
        con.executescript(
            "DROP TABLE users;"
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL"
            " UNIQUE, created_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active');"
            "CREATE INDEX idx_users_status ON users(status);"
            "UPDATE meta SET value = '3' WHERE key = 'schema_version';"
        )
    assert not _checker("c3-02-missing-sqlite")(ws)["users_preserved"]


def test_c3_missing_database_fails_closed(tmp_path):
    ws = _workspace("c3-02-missing-sqlite", tmp_path)
    (ws / "db/app.db").unlink()
    result = _checker("c3-02-missing-sqlite")(ws)
    assert result["migration_unchanged"] and not any(
        v for k, v in result.items() if k != "migration_unchanged"
    )
