"""Negative fixtures for the C3 tool-friction tasks: workarounds that look done but are not."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from tests.taskutil import TASKS, checker, solve, workspace


def _failed(task: str, ws: Path) -> list[str]:
    return [k for k, v in checker(task)(ws).items() if not v]


# ---- c3-01-missing-interpreter --------------------------------------------------------------

C3_01 = "c3-01-missing-interpreter"


def test_c3_01_hand_written_report_with_its_own_threshold(tmp_path):
    ws = workspace(C3_01, tmp_path)
    solve(C3_01, ws, tmp_path)
    path = ws / "out/report.json"
    report = json.loads(path.read_text())
    report["anomalies"] = report["anomalies"][:1]
    path.write_text(json.dumps(report))
    assert _failed(C3_01, ws) == ["anomalies"]


def test_c3_01_rounded_stats_fail(tmp_path):
    ws = workspace(C3_01, tmp_path)
    solve(C3_01, ws, tmp_path)
    path = ws / "out/report.json"
    report = json.loads(path.read_text())
    for stats in report["sensors"].values():
        stats["min"] = round(stats["min"], 1)
        stats["max"] = round(stats["max"], 1)
    path.write_text(json.dumps(report))
    assert _failed(C3_01, ws) == ["sensor_stats"]


def test_c3_01_failed_run_leaves_nothing(tmp_path):
    ws = workspace(C3_01, tmp_path)
    assert _failed(C3_01, ws) == ["report_valid", "sensor_stats", "anomalies"]


# ---- c3-03-flaky-sync -----------------------------------------------------------------------

C3_03 = "c3-03-flaky-sync"
C3_03_MIRROR = TASKS / C3_03 / "environment" / "mirror" / "prices.csv"


def _c3_03_apply(ws: Path) -> None:
    subprocess.run([sys.executable, "bin/apply_prices.py"], cwd=ws, check=True, capture_output=True)


def test_c3_03_sync_then_apply_is_done(tmp_path):
    ws = workspace(C3_03, tmp_path)
    shutil.copyfile(C3_03_MIRROR, ws / "data/prices.csv")
    _c3_03_apply(ws)
    assert _failed(C3_03, ws) == []


def test_c3_03_applying_the_stale_list_looks_updated_but_is_not(tmp_path):
    ws = workspace(C3_03, tmp_path)
    _c3_03_apply(ws)
    assert _failed(C3_03, ws) == ["prices_synced", "active_prices", "as_of_date"]


def test_c3_03_repricing_discontinued_items_fails(tmp_path):
    ws = workspace(C3_03, tmp_path)
    shutil.copyfile(C3_03_MIRROR, ws / "data/prices.csv")
    apply = ws / "bin/apply_prices.py"
    apply.write_text(apply.read_text().replace('not item["discontinued"] and ', ""))
    _c3_03_apply(ws)
    assert _failed(C3_03, ws) == ["discontinued_kept", "apply_script_unchanged"]


# ---- c3-04-stale-lock -----------------------------------------------------------------------

C3_04 = "c3-04-stale-lock"


def test_c3_04_hand_concatenated_bundle_in_alphabetical_order(tmp_path):
    ws = workspace(C3_04, tmp_path)
    solve(C3_04, ws, tmp_path)
    src = sorted((ws / "src").glob("*.js"))
    (ws / "dist/app.bundle.js").write_text("".join(p.read_text() for p in src))
    assert _failed(C3_04, ws) == ["bundle_built"]


def test_c3_04_running_the_tools_directly_leaves_the_lock(tmp_path):
    ws = workspace(C3_04, tmp_path)
    solve(C3_04, ws, tmp_path)
    (ws / "build.lock").write_text("48213\n")
    assert _failed(C3_04, ws) == ["lock_released"]


def test_c3_04_reordering_the_manifest_changes_the_sources(tmp_path):
    ws = workspace(C3_04, tmp_path)
    manifest = ws / "src/manifest.txt"
    manifest.write_text(manifest.read_text().replace("view.js\napi.js", "api.js\nview.js"))
    solve(C3_04, ws, tmp_path)
    assert _failed(C3_04, ws) == ["bundle_built", "build_info", "sources_unchanged"]


def test_c3_04_refusing_at_the_lock_leaves_nothing_built(tmp_path):
    ws = workspace(C3_04, tmp_path)
    assert _failed(C3_04, ws) == ["bundle_built", "build_info", "lock_released"]


# ---- c3-05-missing-yaml ---------------------------------------------------------------------

C3_05 = "c3-05-missing-yaml"


def _c3_05_rendered(ws: Path, tmp_path: Path) -> dict:
    solve(C3_05, ws, tmp_path)
    return json.loads((ws / "out/services.json").read_text())


def _c3_05_write(ws: Path, doc: dict) -> None:
    (ws / "out/services.json").write_text(json.dumps(doc))


def test_c3_05_yaml_merge_semantics_replace_env_instead_of_merging(tmp_path):
    ws = workspace(C3_05, tmp_path)
    doc = _c3_05_rendered(ws, tmp_path)
    for svc in doc["services"]:
        if svc["name"] == "auth":
            svc["env"] = {"ISSUER": svc["env"]["ISSUER"]}
    _c3_05_write(ws, doc)
    assert _failed(C3_05, ws) == ["env_merged"]


def test_c3_05_disabled_service_left_in(tmp_path):
    ws = workspace(C3_05, tmp_path)
    doc = _c3_05_rendered(ws, tmp_path)
    notify = {"name": "notify", "url": "http://notify.internal:8080/healthz", "replicas": 2}
    doc["services"].insert(2, notify | {"env": {"LOG_LEVEL": "info", "REGION": "eu-west"}})
    _c3_05_write(ws, doc)
    assert _failed(C3_05, ws) == ["services_listed"]


def test_c3_05_defaults_not_applied(tmp_path):
    ws = workspace(C3_05, tmp_path)
    doc = _c3_05_rendered(ws, tmp_path)
    for svc in doc["services"]:
        if svc["name"] == "auth":
            svc["url"] = "http://auth.internal:None/healthz"
            svc["replicas"] = None
    _c3_05_write(ws, doc)
    assert _failed(C3_05, ws) == ["urls", "replicas"]


# ---- c3-06-silent-empty-export --------------------------------------------------------------

C3_06 = "c3-06-silent-empty-export"


def _c3_06_export(ws: Path, **env: str) -> None:
    subprocess.run(
        [sys.executable, "bin/export_events.py", "--since", "2026-09-01"],
        cwd=ws,
        check=True,
        capture_output=True,
        env={k: v for k, v in os.environ.items() if k != "EVENTS_DB"} | env,
    )


def test_c3_06_default_path_exports_a_header_and_exits_zero(tmp_path):
    ws = workspace(C3_06, tmp_path)
    _c3_06_export(ws)
    assert (ws / "out/events.csv").read_text() == "id,ts,kind,user\n"
    assert _failed(C3_06, ws) == ["all_events", "only_requested"]


def test_c3_06_exporting_every_kind_is_too_much(tmp_path):
    ws = workspace(C3_06, tmp_path)
    export = ws / "bin/export_events.py"
    export.write_text(
        export.read_text()
        .replace(" AND kind IN (?, ?, ?)", "")
        .replace("(args.since, *BUSINESS)", "(args.since,)")
    )
    _c3_06_export(ws, EVENTS_DB="db/app.db")
    assert _failed(C3_06, ws) == ["only_requested"]
