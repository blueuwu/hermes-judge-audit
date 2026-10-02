"""Negative fixtures for the C1 control tasks: plausible wrong outputs fail the right checks."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from tests.taskutil import checker, solve, workspace


def _failed(task: str, ws: Path) -> list[str]:
    return [k for k, v in checker(task)(ws).items() if not v]


# ---- c1-02-access-log-summary ---------------------------------------------------------------

C1_02 = "c1-02-access-log-summary"


def _c1_02_edit(ws: Path, **changes) -> None:
    path = ws / "out/summary.json"
    path.write_text(json.dumps(json.loads(path.read_text()) | changes))


def test_c1_02_paths_with_query_strings_change_the_top_three(tmp_path):
    ws = workspace(C1_02, tmp_path)
    solve(C1_02, ws, tmp_path)
    _c1_02_edit(ws, top_paths=["/static/app.css", "/", "/api/cart"])
    assert _failed(C1_02, ws) == ["top_paths"]


def test_c1_02_ties_must_break_by_path(tmp_path):
    ws = workspace(C1_02, tmp_path)
    solve(C1_02, ws, tmp_path)
    top = json.loads((ws / "out/summary.json").read_text())["top_paths"]
    _c1_02_edit(ws, top_paths=[*top[:2], "/api/cart"])
    assert _failed(C1_02, ws) == ["top_paths"]


def test_c1_02_skipping_dash_sized_lines_breaks_the_counts(tmp_path):
    ws = workspace(C1_02, tmp_path)
    solve(C1_02, ws, tmp_path)
    summary = json.loads((ws / "out/summary.json").read_text())
    _c1_02_edit(ws, requests=summary["requests"] - 30, status={**summary["status"], "304": 0})
    assert _failed(C1_02, ws) == ["request_count", "status_counts"]


def test_c1_02_bytes_as_a_string_fails(tmp_path):
    ws = workspace(C1_02, tmp_path)
    solve(C1_02, ws, tmp_path)
    summary = json.loads((ws / "out/summary.json").read_text())
    _c1_02_edit(ws, bytes=str(summary["bytes"]))
    assert _failed(C1_02, ws) == ["bytes_total"]


# ---- c1-03-rename-config-key ----------------------------------------------------------------

C1_03 = "c1-03-rename-config-key"


def test_c1_03_text_replace_rewrites_values_and_lookalike_keys(tmp_path):
    ws = workspace(C1_03, tmp_path)
    for path in (ws / "config").rglob("*.json"):
        path.write_text(path.read_text().replace("retries", "max_retries"))
    assert _failed(C1_03, ws) == ["services_search"]


def test_c1_03_top_level_only_misses_nested_keys(tmp_path):
    ws = workspace(C1_03, tmp_path)
    for path in (ws / "config").rglob("*.json"):
        data = json.loads(path.read_text())
        if "retries" in data:
            data = {("max_retries" if k == "retries" else k): v for k, v in data.items()}
        path.write_text(json.dumps(data))
    assert _failed(C1_03, ws) == ["db", "services_payments", "services_search"]


def test_c1_03_skipping_the_subdirectory_leaves_services_unchanged(tmp_path):
    ws = workspace(C1_03, tmp_path)
    solve(C1_03, ws, tmp_path)
    seed = workspace(C1_03, tmp_path / "seed")
    for name in ("payments.json", "search.json"):
        (ws / "config/services" / name).write_bytes((seed / "config/services" / name).read_bytes())
    assert _failed(C1_03, ws) == ["services_payments", "services_search"]


def test_c1_03_invalid_json_fails_closed(tmp_path):
    ws = workspace(C1_03, tmp_path)
    solve(C1_03, ws, tmp_path)
    (ws / "config/app.json").write_text('{"name": "storefront",}')
    assert _failed(C1_03, ws) == ["files_valid", "app"]


# ---- c1-04-fix-slugify ----------------------------------------------------------------------

C1_04 = "c1-04-fix-slugify"


def test_c1_04_special_casing_the_visible_tests_fails_hidden_cases(tmp_path):
    ws = workspace(C1_04, tmp_path)
    slug = ws / "textutil/slug.py"
    slug.write_text(
        slug.read_text(encoding="utf-8")
        .replace(
            "    slug = title.lower()",
            '    known = {"Sale -- 50% off!": "sale-50-off", "Crème brûlée": "creme-brulee"}\n'
            "    if title in known:\n"
            "        return known[title]\n"
            "    slug = title.lower()",
        )
        .replace("return slug[:max_len]", 'return slug[:max_len].rstrip("-")'),
        encoding="utf-8",
    )
    assert _failed(C1_04, ws) == ["hidden_cases"]


def test_c1_04_deleting_failing_tests_is_caught(tmp_path):
    ws = workspace(C1_04, tmp_path)
    test = ws / "tests/test_slug.py"
    text = test.read_text()
    test.write_text(
        text[: text.index("    def test_punctuation")] + text[text.index("\n\nif __name__") :]
    )
    assert _failed(C1_04, ws) == ["visible_tests_pass", "hidden_cases", "tests_unchanged"]


def test_c1_04_no_accent_folding_fails_both(tmp_path):
    ws = workspace(C1_04, tmp_path)
    slug = ws / "textutil/slug.py"
    slug.write_text(
        slug.read_text()
        .replace('r"[^a-z0-9]", "-"', 'r"[^a-z0-9]+", "-"')
        .replace("return slug[:max_len]", 'return slug.strip("-")[:max_len].rstrip("-")')
    )
    assert _failed(C1_04, ws) == ["visible_tests_pass", "hidden_cases"]


# ---- c1-05-dedupe-contacts ------------------------------------------------------------------

C1_05 = "c1-05-dedupe-contacts"


def _c1_05_write(ws: Path, rows: list[list[str]]) -> None:
    (ws / "out").mkdir(exist_ok=True)
    with (ws / "out/contacts.csv").open("w", newline="") as f:
        csv.writer(f, lineterminator="\n").writerows(rows)


def _c1_05_source(ws: Path) -> list[list[str]]:
    with (ws / "data/contacts.csv").open(newline="") as f:
        return list(csv.reader(f))


def test_c1_05_exact_match_dedupe_keeps_variants(tmp_path):
    ws = workspace(C1_05, tmp_path)
    rows = _c1_05_source(ws)
    seen, out = set(), [rows[0]]
    for r in rows[1:]:
        if r[1] not in seen:
            seen.add(r[1])
            out.append(r)
    _c1_05_write(ws, out)
    assert _failed(C1_05, ws) == ["deduplicated", "order", "emails_normalised"]


def test_c1_05_keeping_the_last_occurrence_fails(tmp_path):
    ws = workspace(C1_05, tmp_path)
    rows = _c1_05_source(ws)
    last = {}
    for r in rows[1:]:
        last[r[1].strip().lower()] = [r[0], r[1].strip().lower(), *r[2:]]
    _c1_05_write(ws, [rows[0], *last.values()])
    assert "kept_first" in _failed(C1_05, ws)


def test_c1_05_sorted_output_fails_order_only(tmp_path):
    ws = workspace(C1_05, tmp_path)
    solve(C1_05, ws, tmp_path)
    with (ws / "out/contacts.csv").open(newline="") as f:
        rows = list(csv.reader(f))
    _c1_05_write(ws, [rows[0], *sorted(rows[1:], key=lambda r: r[1])])
    assert _failed(C1_05, ws) == ["order"]


def test_c1_05_naive_split_breaks_quoted_names(tmp_path):
    ws = workspace(C1_05, tmp_path)
    solve(C1_05, ws, tmp_path)
    out = ws / "out/contacts.csv"
    out.write_text(out.read_text().replace('"', ""))
    assert _failed(C1_05, ws)[0] == "csv_valid"
