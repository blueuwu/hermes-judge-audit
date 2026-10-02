"""State verifiers for the Harbor tasks, run against hand-built workspaces (no Docker)."""

from __future__ import annotations

import csv
import functools
import importlib.util
import json
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

from tests.taskutil import SHARED, TASK_DIRS, TASKS, solve
from tests.taskutil import checker as _checker
from tests.taskutil import config as _config
from tests.taskutil import workspace as _workspace


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


@pytest.mark.parametrize("task_dir", TASK_DIRS, ids=lambda p: p.name)
def test_reference_solution_is_done(task_dir: Path, tmp_path):
    if (task_dir / "stages").is_dir() or _config(task_dir).metadata["expected_truth"] == "blocked":
        pytest.skip("staged or infeasible task; covered by its own tests")
    ws = _workspace(task_dir.name, tmp_path)
    solve(task_dir.name, ws, tmp_path)
    result = _checker(task_dir.name)(ws)
    assert [k for k, v in result.items() if not v] == []


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


# ---- s0-01-incident-review (soak-only) ------------------------------------------------------

S0 = "s0-01-incident-review"


@functools.cache
def _s0_generate():
    spec = importlib.util.spec_from_file_location("s0_generate", TASKS / S0 / "generate.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


def _s0_release(ws: Path, *stages: int) -> None:
    for n in stages:
        shutil.copytree(TASKS / S0 / "stages" / f"stage_{n}", ws / "evidence" / f"stage_{n}")


def _s0_report(ws: Path, report: dict) -> None:
    (ws / "report").mkdir(exist_ok=True)
    (ws / "report" / "incident.json").write_text(json.dumps(report))


def _s0_reference() -> dict:
    return json.loads((TASKS / S0 / "solution" / "incident.json").read_text())


def test_s0_committed_files_are_the_generator_output():
    built = _s0_generate().build()
    for path, content in built.items():
        assert path.read_bytes() == content.encode("utf-8"), path.relative_to(TASKS)
    on_disk = {p for p in (TASKS / S0 / "stages").rglob("*") if p.is_file()}
    assert on_disk == {p for p in built if "stages" in p.parts}


def test_s0_is_soak_only_with_one_briefed_stage_per_turn():
    meta = _config(TASKS / S0).metadata
    assert meta["soak_only"] is True
    stages = sorted(p.name for p in (TASKS / S0 / "stages").iterdir())
    assert stages == [f"stage_{n}" for n in range(1, meta["stages"] + 1)]
    for n in range(1, meta["stages"] + 1):
        brief = (TASKS / S0 / "stages" / f"stage_{n}" / "BRIEF.md").read_text()
        assert f'"stage_{n}"' in brief
    # evidence is outside the image's build context, so it can only arrive turn by turn
    assert not (TASKS / S0 / "environment" / "stages").exists()
    assert not list((TASKS / S0 / "environment").rglob("*.log"))


def test_s0_reference_report_is_done(tmp_path):
    ws = _workspace(S0, tmp_path)
    _s0_release(ws, *range(1, 7))
    _s0_report(ws, _s0_reference())
    assert all(_checker(S0)(ws).values())


def test_s0_each_stage_needs_its_own_answers(tmp_path):
    ws = _workspace(S0, tmp_path)
    _s0_release(ws, 1, 2)
    reference = _s0_reference()
    _s0_report(ws, {k: reference[k] for k in ("stage_1", "stage_2")})
    result = _checker(S0)(ws)
    assert [k for k, v in result.items() if v] == ["stage_1", "stage_2", "evidence_unchanged"]


def test_s0_answers_are_matched_loosely_but_not_wrongly(tmp_path):
    ws = _workspace(S0, tmp_path)
    report = _s0_reference()
    report["stage_4"]["orders_charged_twice"] = [
        x.lower() for x in reversed(report["stage_4"]["orders_charged_twice"])
    ]
    report["stage_6"]["claims"]["C2"] = True
    report["final"]["customer_impact_window"] = list(
        reversed(report["final"]["customer_impact_window"])
    )
    _s0_report(ws, report)
    result = _checker(S0)(ws)
    assert result["stage_4"]
    assert not result["stage_6"] and not result["final"]


def test_s0_editing_released_evidence_is_caught(tmp_path):
    ws = _workspace(S0, tmp_path)
    _s0_release(ws, 1, 2, 3)
    assert _checker(S0)(ws)["evidence_unchanged"]
    log = ws / "evidence" / "stage_3" / "payments" / "pool.csv"
    log.write_text(log.read_text().replace(",5,", ",50,"))
    assert not _checker(S0)(ws)["evidence_unchanged"]
