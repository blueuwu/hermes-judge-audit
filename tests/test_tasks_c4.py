"""Checks for the C4 tasks adapted from Terminal-Bench 2.0: stricter than upstream's tests."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.taskutil import TASKS, checker_module, solve, workspace

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test User",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test User",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        env=os.environ | GIT_ENV,
    )
    return proc.stdout.strip()


def _failed(module, ws: Path) -> list[str]:
    return [k for k, v in module.check(ws).items() if not v]


# ---- c4-01-fix-git --------------------------------------------------------------------------

C4_01 = "c4-01-fix-git"
STANFORD = {
    "_includes/about.md": "I am at Stanford.\n",
    "_layouts/default.html": "<html>v2</html>\n",
}


def _write(repo: Path, files: dict[str, str]) -> None:
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text)


@pytest.fixture
def c4_01(tmp_path, monkeypatch):
    """A small stand-in for the upstream repository, in the same state, with its hashes."""
    if shutil.which("git") is None:
        pytest.skip("git not available")
    ws = tmp_path / "app"
    repo = ws / "personal-site"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "master")
    _write(
        repo,
        {
            "_includes/about.md": "On the job market.\n",
            "_layouts/default.html": "<html>v1</html>\n",
        },
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "CV Update")
    _write(repo, {"_includes/about.md": "Off the job market!\n"})
    _git(repo, "commit", "-q", "-am", "off the job market woo")
    master = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "HEAD~1")
    _write(repo, STANFORD)
    _git(repo, "commit", "-q", "-am", "Move to Stanford")
    _git(repo, "checkout", "-q", "master")
    module = checker_module(C4_01)
    monkeypatch.setattr(
        module,
        "EXPECTED",
        {
            "about_sha256": hashlib.sha256(
                STANFORD["_includes/about.md"].strip().encode()
            ).hexdigest(),
            "layout_sha256": hashlib.sha256(
                STANFORD["_layouts/default.html"].strip().encode()
            ).hexdigest(),
            "master_before": master,
        },
    )
    monkeypatch.setattr(
        module,
        "_git",
        lambda r, *a: subprocess.run(
            ["git", "-C", str(r), *a], capture_output=True, env=os.environ | GIT_ENV
        ),
    )
    return module, ws, repo


def _lost(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD@{1}")


def test_c4_01_seed_has_nothing_restored(c4_01):
    module, ws, _ = c4_01
    assert _failed(module, ws) == ["about_restored", "layout_restored", "committed_on_master"]


def test_c4_01_merge_resolved_for_the_lost_commit_is_done(c4_01):
    module, ws, repo = c4_01
    _git(repo, "merge", "-q", "-X", "theirs", "-m", "Merge lost changes", _lost(repo))
    assert _failed(module, ws) == []


def test_c4_01_files_copied_but_not_committed(c4_01):
    module, ws, repo = c4_01
    _write(repo, STANFORD)
    assert _failed(module, ws) == ["committed_on_master", "tree_clean"]


def test_c4_01_conflict_resolved_for_master(c4_01):
    module, ws, repo = c4_01
    _git(repo, "merge", "-q", "-X", "ours", "-m", "Merge lost changes", _lost(repo))
    assert _failed(module, ws) == ["about_restored", "committed_on_master"]


def test_c4_01_unfinished_merge_with_markers(c4_01):
    module, ws, repo = c4_01
    _git(repo, "merge", "-q", _lost(repo))
    assert _failed(module, ws) == ["about_restored", "committed_on_master", "tree_clean"]


def test_c4_01_resetting_master_to_the_lost_commit_drops_history(c4_01):
    module, ws, repo = c4_01
    _git(repo, "reset", "-q", "--hard", _lost(repo))
    assert _failed(module, ws) == ["master_history_kept"]


# ---- c4-02-sqlite-db-truncate ---------------------------------------------------------------

C4_02 = "c4-02-sqlite-db-truncate"


def _c4_02(tmp_path: Path, rows: list[dict]) -> list[str]:
    ws = workspace(C4_02, tmp_path)
    (ws / "recover.json").write_text(json.dumps(rows))
    return _failed(checker_module(C4_02), ws)


UPSTREAM = [
    {"word": f"testword0{i}", "value": v}
    for i, v in zip(range(2, 10), [10, 25, 42, 50, 75, 99, 99.99, 0.5], strict=True)
]


def test_c4_02_seven_of_eight_passes_upstream_but_not_here(tmp_path):
    assert _c4_02(tmp_path, UPSTREAM[:7]) == ["recovered_all"]


def test_c4_02_the_two_extra_intact_rows_are_accepted(tmp_path):
    extra = [{"word": "testword00", "value": 1}, {"word": "testword01", "value": 2}]
    assert _c4_02(tmp_path, extra + UPSTREAM) == []


def test_c4_02_invented_rows_fail(tmp_path):
    assert _c4_02(tmp_path, [*UPSTREAM, {"word": "testword10", "value": 0}]) == ["no_invented_rows"]


def test_c4_02_values_as_strings_fail_the_format(tmp_path):
    rows = [r | {"value": str(r["value"])} for r in UPSTREAM]
    assert _c4_02(tmp_path, rows) == ["format_valid", "recovered_all", "no_invented_rows"]


# ---- c4-03-cobol-modernization --------------------------------------------------------------

C4_03 = "c4-03-cobol-modernization"


def _c4_03(tmp_path: Path, *edits: tuple[str, str]) -> list[str]:
    ws = workspace(C4_03, tmp_path)
    solve(C4_03, ws, tmp_path)
    program = ws / "program.py"
    text = program.read_text()
    for old, new in edits:
        assert old in text, old
        text = text.replace(old, new)
    program.write_text(text)
    return _failed(checker_module(C4_03), ws)


def test_c4_03_signed_balances_break_only_the_overdraft(tmp_path):
    edit = ("balance = abs(balance - amount) % 10**10", "balance = max(balance - amount, 0)")
    assert _c4_03(tmp_path, edit) == ["overdraft_quirk"]


def test_c4_03_rewriting_the_ledger_instead_of_appending(tmp_path):
    edit = ('open(APP / "data/TRANSACTIONS.DAT", "a")', 'open(APP / "data/TRANSACTIONS.DAT", "w")')
    assert _c4_03(tmp_path, edit) == ["example_matches", "ledger_append"]


def test_c4_03_skipping_the_owner_check(tmp_path):
    edit = (" and any(r[24:28] == seller for r in book)", "")
    assert _c4_03(tmp_path, edit) == ["validation_rules"]


def test_c4_03_no_program_fails_everything(tmp_path):
    ws = workspace(C4_03, tmp_path)
    assert all(not v for v in checker_module(C4_03).check(ws).values())


# ---- c4-04-regex-log ------------------------------------------------------------------------

C4_04 = "c4-04-regex-log"
IPV4 = r"(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)"


def _c4_04(tmp_path: Path, pattern: str) -> list[str]:
    ws = workspace(C4_04, tmp_path)
    (ws / "regex.txt").write_text(pattern + "\n")
    return _failed(checker_module(C4_04), ws)


def test_c4_04_ignoring_month_lengths_passes_upstream_but_not_calendar(tmp_path):
    lazy = (
        rf"(?=.*(?:^|[^0-9A-Za-z]){IPV4}(?=$|[^0-9A-Za-z]))"
        r".*(?:^|[^0-9A-Za-z])(\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01]))(?=$|[^0-9A-Za-z])"
    )
    assert _c4_04(tmp_path, lazy) == ["calendar_rules"]


def test_c4_04_no_boundaries_on_the_ip(tmp_path):
    loose = (
        rf"(?=.*{IPV4})"
        r".*(?:^|[^0-9A-Za-z])(\d{4}-(?:(?:01|03|05|07|08|10|12)-(?:0[1-9]|[12]\d|3[01])"
        r"|(?:04|06|09|11)-(?:0[1-9]|[12]\d|30)|02-(?:0[1-9]|1\d|2\d)))(?=$|[^0-9A-Za-z])"
    )
    assert _c4_04(tmp_path, loose) == ["upstream_cases"]


def test_c4_04_no_boundary_after_the_date(tmp_path):
    glued = (
        rf"(?=.*(?:^|[^0-9A-Za-z]){IPV4}(?=$|[^0-9A-Za-z]))"
        r".*(?:^|[^0-9A-Za-z])(\d{4}-(?:(?:01|03|05|07|08|10|12)-(?:0[1-9]|[12]\d|3[01])"
        r"|(?:04|06|09|11)-(?:0[1-9]|[12]\d|30)|02-(?:0[1-9]|1\d|2\d)))"
    )
    assert _c4_04(tmp_path, glued) == ["upstream_cases", "boundary_rules"]


def test_c4_04_invalid_pattern(tmp_path):
    assert _c4_04(tmp_path, "(unclosed") == [
        "regex_valid",
        "upstream_cases",
        "calendar_rules",
        "boundary_rules",
    ]


# ---- c4-05-log-summary-date-ranges ----------------------------------------------------------

C4_05 = "c4-05-log-summary-date-ranges"


@pytest.fixture
def c4_05(tmp_path):
    """The workspace with the logs the task image generates at build time."""
    ws = workspace(C4_05, tmp_path)
    generator = (TASKS / C4_05 / "environment" / "log_generator_deterministic.py").read_text()
    script = tmp_path / "gen.py"
    script.write_text(generator.replace('"/app/logs"', repr((ws / "logs").as_posix())))
    subprocess.run([sys.executable, str(script)], check=True)
    return ws


def _c4_05_rows(ws: Path) -> list[list[str]]:
    return [line.split(",") for line in (ws / "summary.csv").read_text().splitlines()]


def _c4_05_write(ws: Path, rows: list[list[str]]) -> None:
    (ws / "summary.csv").write_text("".join(",".join(r) + "\n" for r in rows))


def test_c4_05_reference_reproduces_upstream_counts(c4_05, tmp_path):
    solve(C4_05, c4_05, tmp_path)
    assert _failed(checker_module(C4_05), c4_05) == []


def test_c4_05_off_by_one_week_fails_that_period_only(c4_05, tmp_path):
    solve(C4_05, c4_05, tmp_path)
    rows = _c4_05_rows(c4_05)
    for r in rows:
        if r[0] == "last_7_days":
            r[2] = str(int(r[2]) + 1)
    _c4_05_write(c4_05, rows)
    assert _failed(checker_module(C4_05), c4_05) == ["last_7_days"]


def test_c4_05_counting_every_line_that_mentions_error(c4_05, tmp_path):
    solve(C4_05, c4_05, tmp_path)
    mentions = {}
    for path in (c4_05 / "logs").glob("*.log"):
        mentions[path.name] = sum("ERROR" in line for line in path.read_text().splitlines())
    rows = _c4_05_rows(c4_05)
    for r in rows:
        if r[:2] == ["total", "ERROR"]:
            r[2] = str(sum(mentions.values()))
    _c4_05_write(c4_05, rows)
    assert _failed(checker_module(C4_05), c4_05) == ["total"]
