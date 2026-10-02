"""Negative fixtures for the C2 multi-part tasks: each partial completion fails its own checks."""

from __future__ import annotations

import json
from pathlib import Path

from tests.taskutil import checker, solve, workspace


def _failed(task: str, ws: Path) -> list[str]:
    return [k for k, v in checker(task)(ws).items() if not v]


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new), encoding="utf-8")


# ---- c2-01-rename-function ------------------------------------------------------------------

C2_01 = "c2-01-rename-function"


def test_c2_01_missing_the_cli_and_docs_leaves_two_parts_undone(tmp_path):
    ws = workspace(C2_01, tmp_path)
    solve(C2_01, ws, tmp_path)
    _edit(ws / "billing/cli.py", "totals.compute_total(", "totals.calc_total(")
    _edit(ws / "docs/API.md", "## `billing.totals.compute_total", "## `billing.totals.calc_total")
    assert _failed(C2_01, ws) == ["callers_updated", "docs_updated"]


def test_c2_01_plain_alias_without_a_warning_fails(tmp_path):
    ws = workspace(C2_01, tmp_path)
    solve(C2_01, ws, tmp_path)
    totals = ws / "billing/totals.py"
    text = totals.read_text()
    totals.write_text(
        text[: text.index("\n\ndef calc_total(")] + "\n\ncalc_total = compute_total\n"
    )
    assert _failed(C2_01, ws) == ["deprecated_alias"]


def test_c2_01_rename_without_alias_or_changelog(tmp_path):
    ws = workspace(C2_01, tmp_path)
    solve(C2_01, ws, tmp_path)
    totals = ws / "billing/totals.py"
    text = totals.read_text()
    totals.write_text(text[: text.index("\n\ndef calc_total(")] + "\n")
    seed = workspace(C2_01, tmp_path / "seed")
    (ws / "CHANGELOG.md").write_bytes((seed / "CHANGELOG.md").read_bytes())
    assert _failed(C2_01, ws) == ["deprecated_alias", "changelog_entry"]


def test_c2_01_changelog_entry_under_a_released_version_does_not_count(tmp_path):
    ws = workspace(C2_01, tmp_path)
    solve(C2_01, ws, tmp_path)
    seed = workspace(C2_01, tmp_path / "seed")
    (ws / "CHANGELOG.md").write_bytes((seed / "CHANGELOG.md").read_bytes())
    _edit(
        ws / "CHANGELOG.md", "## 2.3.0 - 2026-09-12\n", "## 2.3.0 - 2026-09-12\n\n- compute_total\n"
    )
    assert _failed(C2_01, ws) == ["changelog_entry"]


def test_c2_01_seed_passes_its_tests_but_nothing_else(tmp_path):
    ws = workspace(C2_01, tmp_path)
    assert _failed(C2_01, ws) == [
        "renamed_definition",
        "callers_updated",
        "deprecated_alias",
        "docs_updated",
        "changelog_entry",
    ]


# ---- c2-02-add-dry-run-flag -----------------------------------------------------------------

C2_02 = "c2-02-add-dry-run-flag"


def test_c2_02_dry_run_that_still_deletes_fails(tmp_path):
    ws = workspace(C2_02, tmp_path)
    solve(C2_02, ws, tmp_path)
    _edit(
        ws / "tools/cleanup.py",
        '            print(f"would delete {path}")\n            continue\n',
        '            print(f"would delete {path}")\n',
    )
    failed = _failed(C2_02, ws)
    assert failed[0] == "dry_run_deletes_nothing"
    assert "default_unchanged" not in failed


def test_c2_02_flag_only_without_docs_or_test(tmp_path):
    ws = workspace(C2_02, tmp_path)
    solve(C2_02, ws, tmp_path)
    seed = workspace(C2_02, tmp_path / "seed")
    for name in ("README.md", "tests/test_cleanup.py"):
        (ws / name).write_bytes((seed / name).read_bytes())
    assert _failed(C2_02, ws) == ["readme_documents_flag", "test_added"]


def test_c2_02_changing_the_default_output_fails(tmp_path):
    ws = workspace(C2_02, tmp_path)
    solve(C2_02, ws, tmp_path)
    _edit(ws / "tools/cleanup.py", 'print(f"deleted {path}")', 'print(f"removed {path}")')
    assert "default_unchanged" in _failed(C2_02, ws)


def test_c2_02_seed_has_no_flag(tmp_path):
    ws = workspace(C2_02, tmp_path)
    assert _failed(C2_02, ws) == [
        "dry_run_deletes_nothing",
        "dry_run_lists_files",
        "readme_documents_flag",
        "test_added",
    ]


# ---- c2-03-release-bump ---------------------------------------------------------------------

C2_03 = "c2-03-release-bump"


def test_c2_03_blind_replace_rewrites_the_pin_and_history(tmp_path):
    ws = workspace(C2_03, tmp_path)
    for path in ws.rglob("*"):
        if path.is_file():
            path.write_text(path.read_text().replace("1.4.2", "1.5.0"))
    _edit(ws / "docs/conf.py", 'version = "1.4"', 'version = "1.5"')
    _edit(ws / "CHANGELOG.md", "## Unreleased\n", "## Unreleased\n\n## 1.5.0 - 2026-10-02\n")
    assert _failed(C2_03, ws) == ["nothing_else_changed"]


def test_c2_03_missing_the_docs_short_version_and_badge(tmp_path):
    ws = workspace(C2_03, tmp_path)
    solve(C2_03, ws, tmp_path)
    _edit(ws / "docs/conf.py", 'version = "1.5"', 'version = "1.4"')
    _edit(ws / "README.md", "version-1.5.0-blue", "version-1.4.2-blue")
    assert _failed(C2_03, ws) == ["docs_version", "readme_badge"]


def test_c2_03_renaming_unreleased_instead_of_keeping_it(tmp_path):
    ws = workspace(C2_03, tmp_path)
    solve(C2_03, ws, tmp_path)
    _edit(ws / "CHANGELOG.md", "## Unreleased\n\n", "")
    assert _failed(C2_03, ws) == ["unreleased_empty"]


def test_c2_03_entries_left_under_unreleased(tmp_path):
    ws = workspace(C2_03, tmp_path)
    solve(C2_03, ws, tmp_path)
    _edit(
        ws / "CHANGELOG.md",
        "## Unreleased\n\n## 1.5.0 - 2026-10-02\n",
        "## 1.5.0 - 2026-10-02\n\n## Unreleased\n",
    )
    assert _failed(C2_03, ws) == ["changelog_section", "unreleased_empty"]


# ---- c2-04-settings-migration ---------------------------------------------------------------

C2_04 = "c2-04-settings-migration"


def _c2_04_rewrite(ws: Path, change) -> None:
    path = ws / "config/settings.json"
    doc = json.loads(path.read_text())
    change(doc)
    path.write_text(json.dumps(doc))


def test_c2_04_timeouts_left_in_seconds(tmp_path):
    ws = workspace(C2_04, tmp_path)
    solve(C2_04, ws, tmp_path)

    def seconds(doc):
        for section in ("server", "database", "cache"):
            doc[section]["timeout_ms"] = doc[section]["timeout_ms"] // 1000

    _c2_04_rewrite(ws, seconds)
    assert _failed(C2_04, ws) == ["timeouts_ms"]


def test_c2_04_legacy_keys_kept_and_no_schema_version(tmp_path):
    ws = workspace(C2_04, tmp_path)
    solve(C2_04, ws, tmp_path)

    def partial(doc):
        doc["server"]["legacy_mode"] = False
        doc["cache"]["legacy_keys"] = True
        del doc["schema_version"]

    _c2_04_rewrite(ws, partial)
    assert _failed(C2_04, ws) == ["sections", "removed_keys", "schema_version"]


def test_c2_04_values_left_as_strings(tmp_path):
    ws = workspace(C2_04, tmp_path)
    solve(C2_04, ws, tmp_path)

    def strings(doc):
        for section in ("server", "database", "cache", "features"):
            for key, value in doc[section].items():
                if key != "timeout_ms" and not isinstance(value, str):
                    doc[section][key] = {True: "yes", False: "no"}.get(value, str(value))

    _c2_04_rewrite(ws, strings)
    assert _failed(C2_04, ws) == ["booleans", "numbers"]


# ---- c2-05-month-end-close ------------------------------------------------------------------

C2_05 = "c2-05-month-end-close"


def test_c2_05_strict_date_glob_misses_the_late_file(tmp_path):
    ws = workspace(C2_05, tmp_path)
    late = ws / "sales/2026-09-30-late.csv"
    hidden = tmp_path / "late.csv"
    late.rename(hidden)
    solve(C2_05, ws, tmp_path)
    hidden.rename(late)
    assert _failed(C2_05, ws) == [
        "summary_correct",
        "september_archived",
        "others_untouched",
        "manifest_correct",
    ]


def test_c2_05_copying_instead_of_moving_leaves_september_in_sales(tmp_path):
    ws = workspace(C2_05, tmp_path)
    seed = workspace(C2_05, tmp_path / "seed")
    solve(C2_05, ws, tmp_path)
    for path in (ws / "archive/2026-09").glob("*.csv"):
        (ws / "sales" / path.name).write_bytes((seed / "sales" / path.name).read_bytes())
    assert _failed(C2_05, ws) == ["september_archived", "others_untouched"]


def test_c2_05_manifest_with_paths_instead_of_names(tmp_path):
    ws = workspace(C2_05, tmp_path)
    solve(C2_05, ws, tmp_path)
    manifest = ws / "archive/2026-09/MANIFEST.txt"
    manifest.write_text(manifest.read_text().replace("  2026", "  sales/2026"))
    assert _failed(C2_05, ws) == ["manifest_correct"]


def test_c2_05_dropping_the_refund_row_changes_one_region(tmp_path):
    ws = workspace(C2_05, tmp_path)
    solve(C2_05, ws, tmp_path)
    path = ws / "out/2026-09-summary.csv"
    rows = path.read_text().splitlines()
    region, orders, revenue = rows[1].split(",")
    rows[1] = f"{region},{int(orders) - 1},{revenue}"
    path.write_text("\n".join(rows) + "\n")
    assert _failed(C2_05, ws) == ["summary_correct"]
