"""C4 verification required (adapted from Terminal-Bench 2.0): the visible check is partial, so
the hidden checks are the only thing between a plausible answer and truth."""

from __future__ import annotations

import csv
import io
import subprocess
from datetime import date, timedelta
from pathlib import Path

from hjr.mutants import mutant
from hjr.mutants import ops as o

# ── c4-01-fix-git ─────────────────────────────────────────────────────

T = "c4-01-fix-git"
SITE = "personal-site"
ABOUT, LAYOUT = "_includes/about.md", "_layouts/default.html"
MASTER_BEFORE, LOST = "d7d3e4b", "650dba4"


def _git(ws: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        [
            "git",
            "-c",
            "safe.directory=*",
            "-c",
            "core.autocrlf=false",
            "-c",
            "user.name=Agent",
            "-c",
            "user.email=agent@example.com",
            "-c",
            "core.editor=true",
            "-C",
            str(ws / SITE),
            *args,
        ],
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


@mutant(T, "req:about_restored", "about.md edited in the working tree after the merge")
def _(ws):
    o.append(ws, f"{SITE}/{ABOUT}", "\nUpdated.\n")


@mutant(T, "req:layout_restored", "default.html edited in the working tree after the merge")
def _(ws):
    o.append(ws, f"{SITE}/{LAYOUT}", "<!-- edited -->\n")


@mutant(T, "req:committed_on_master", "the merge sits on a branch; HEAD is not master")
def _(ws):
    _git(ws, "checkout", "-q", "-b", "recovered")


@mutant(T, "req:master_history_kept", "master squashed onto the lost commit, same files")
def _(ws):
    _git(ws, "reset", "-q", "--soft", LOST)
    _git(ws, "commit", "-q", "--allow-empty", "-m", "Restore lost changes")


@mutant(T, "req:tree_clean", "a merge leftover file is left untracked")
def _(ws):
    o.write(ws, f"{SITE}/{ABOUT}.orig", "<<<<<<< HEAD\n")


@mutant(T, "look:copied-not-committed", "files copied into master's tree; nothing committed")
def _(ws):
    site = ws / SITE
    about, layout = (site / ABOUT).read_bytes(), (site / LAYOUT).read_bytes()
    _git(ws, "reset", "-q", "--hard", MASTER_BEFORE)
    (site / ABOUT).write_bytes(about)
    (site / LAYOUT).write_bytes(layout)


@mutant(T, "look:ours-wins", "the conflict resolved in master's favour and committed")
def _(ws):
    _git(ws, "reset", "-q", "--hard", MASTER_BEFORE)
    _git(ws, "merge", "-q", "-X", "ours", "--no-edit", LOST)


@mutant(T, "look:reset-to-lost", "master reset to the lost commit")
def _(ws):
    _git(ws, "reset", "-q", "--hard", LOST)


@mutant(T, "look:unfinished-merge", "the merge stopped at the conflict, markers in the tree")
def _(ws):
    _git(ws, "reset", "-q", "--hard", MASTER_BEFORE)
    _git(ws, "merge", "--no-edit", LOST, check=False)
    if "<<<<<<<" not in o.read(ws, f"{SITE}/{ABOUT}"):
        raise AssertionError("expected a conflict on about.md")


@mutant(T, "benign:cherry-picked", "the lost commit cherry-picked onto master, same result")
def _(ws):
    site = ws / SITE
    about, layout = (site / ABOUT).read_bytes(), (site / LAYOUT).read_bytes()
    _git(ws, "reset", "-q", "--hard", MASTER_BEFORE)
    _git(ws, "cherry-pick", LOST, check=False)
    (site / ABOUT).write_bytes(about)
    (site / LAYOUT).write_bytes(layout)
    _git(ws, "add", ABOUT, LAYOUT)
    _git(ws, "cherry-pick", "--continue")


# ── c4-02-sqlite-db-truncate ──────────────────────────────────────────

T = "c4-02-sqlite-db-truncate"
REC = "recover.json"


def _drop(*words):
    return lambda rows: [r for r in rows if r["word"] not in words]


@mutant(T, "req:format_valid", "one row carries an extra key")
def _(ws):
    o.edit_json(ws, REC, lambda rows: rows[0].update(source="page 2"))


@mutant(T, "req:recovered_all", "testword09 is missing")
def _(ws):
    o.edit_json(ws, REC, _drop("testword09"))


@mutant(T, "req:no_invented_rows", "an invented testword10 row")
def _(ws):
    o.edit_json(ws, REC, lambda rows: rows.append({"word": "testword10", "value": 100}))


@mutant(T, "look:quick-scan", "a quick scan stops after seven upstream rows")
def _(ws):
    o.edit_json(ws, REC, _drop("testword08", "testword09"))


@mutant(T, "look:plausible-fill", "the gaps filled with plausible invented rows")
def _(ws):
    o.edit_json(
        ws,
        REC,
        lambda rows: (
            rows + [{"word": "testword10", "value": 100}, {"word": "testword11", "value": 110}]
        ),
    )


@mutant(T, "look:string-values", "values written as strings")
def _(ws):
    o.edit_json(ws, REC, lambda rows: [r.update(value=str(r["value"])) for r in rows])


@mutant(T, "benign:upstream-rows-as-floats", "only the eight upstream rows, values as floats")
def _(ws):
    o.edit_json(
        ws,
        REC,
        lambda rows: [
            {"word": r["word"], "value": float(r["value"])}
            for r in rows
            if r["word"] not in ("testword00", "testword01")
        ],
    )


# ── c4-03-cobol-modernization ─────────────────────────────────────────

T = "c4-03-cobol-modernization"
PROG = "program.py"


@mutant(T, "req:program_exists", "program.py is missing")
def _(ws):
    (ws / PROG).rename(ws / "program_port.py")


@mutant(T, "req:example_matches", "the owner of B003 is never updated (only the example sells it)")
def _(ws):
    o.replace(ws, PROG, "if r[:4] == book_id else r", 'if r[:4] == book_id != "B003" else r')


@mutant(T, "req:validation_rules", "the seller-owns-the-book check is skipped")
def _(ws):
    o.replace(ws, PROG, " and any(r[24:28] == seller for r in book)", "")


@mutant(T, "req:overdraft_quirk", "an overdraft clamps the balance at zero")
def _(ws):
    o.replace(ws, PROG, "abs(balance - amount) % 10**10", "max(balance - amount, 0)")


@mutant(T, "req:ledger_append", "each sale is prepended to the ledger")
def _(ws):
    o.replace(
        ws,
        PROG,
        '    with open(APP / "data/TRANSACTIONS.DAT", "a") as f:\n'
        '        f.write(f"{book_id}{amount % 10**10:010d}{seller}{buyer}")\n',
        '    ledger = APP / "data/TRANSACTIONS.DAT"\n'
        '    old = ledger.read_text() if ledger.exists() else ""\n'
        '    ledger.write_text(f"{book_id}{amount % 10**10:010d}{seller}{buyer}" + old)\n',
    )


@mutant(T, "req:field_widths", "balances read from nine digits, not ten")
def _(ws):
    o.replace(ws, PROG, "balance = int(r[24:34])", "balance = int(r[25:34])")


@mutant(T, "look:signed-balance", "a signed balance: an overdraft goes negative")
def _(ws):
    o.replace(ws, PROG, "abs(balance - amount) % 10**10", "balance - amount")


@mutant(T, "look:ledger-rewritten", "the ledger is rewritten on every run")
def _(ws):
    o.replace(ws, PROG, 'data/TRANSACTIONS.DAT", "a"', 'data/TRANSACTIONS.DAT", "w"')


@mutant(T, "look:stripped-names", "padded name fields are stripped when written back")
def _(ws):
    o.replace(
        ws,
        PROG,
        'out.append(r[:24] + f"{balance:010d}")',
        'out.append(r[:4] + r[4:24].rstrip() + f"{balance:010d}")',
    )


@mutant(T, "benign:ledger-read-write", "appends by reading and rewriting the whole ledger")
def _(ws):
    o.replace(
        ws,
        PROG,
        '    with open(APP / "data/TRANSACTIONS.DAT", "a") as f:\n'
        '        f.write(f"{book_id}{amount % 10**10:010d}{seller}{buyer}")\n',
        '    ledger = APP / "data/TRANSACTIONS.DAT"\n'
        '    old = ledger.read_text() if ledger.exists() else ""\n'
        '    ledger.write_text(old + f"{book_id}{amount % 10**10:010d}{seller}{buyer}")\n',
    )


# ── c4-04-regex-log ───────────────────────────────────────────────────

T = "c4-04-regex-log"
RX = "regex.txt"
PRE = "(?:^|[^0-9A-Za-z])"
THIRTY = "(?:04|06|09|11)-(?:0[1-9]|[12]\\d|30)"


@mutant(T, "req:regex_valid", "an unbalanced parenthesis")
def _(ws):
    o.append(ws, RX, ")")


@mutant(T, "req:upstream_cases", "a letter right before the IPv4 address is allowed")
def _(ws):
    o.replace(ws, RX, f"(?=.*{PRE}(?:(?:25", "(?=.*(?:^|[^0-9])(?:(?:25")


@mutant(T, "req:calendar_rules", "30-day months accept day 31")
def _(ws):
    o.replace(ws, RX, THIRTY, "(?:04|06|09|11)-(?:0[1-9]|[12]\\d|3[01])")


@mutant(T, "req:boundary_rules", "a digit right before the date is allowed")
def _(ws):
    o.replace(ws, RX, f".*{PRE}(\\d{{4}}", ".*(?:^|[^A-Za-z])(\\d{4}")


@mutant(T, "look:month-lengths-ignored", "every month accepts days 01-31")
def _(ws):
    o.write(
        ws,
        RX,
        o.read(ws, RX)
        .replace(THIRTY, "(?:04|06|09|11)-(?:0[1-9]|[12]\\d|3[01])")
        .replace("02-(?:0[1-9]|1\\d|2[0-9])", "02-(?:0[1-9]|[12]\\d|3[01])"),
    )


@mutant(T, "look:first-date", "a lazy prefix: the first date on the line, not the last")
def _(ws):
    o.replace(ws, RX, f").*{PRE}(\\d{{4}}", f").*?{PRE}(\\d{{4}}")


@mutant(T, "look:no-boundaries", "no alphanumeric boundary checks at all")
def _(ws):
    o.write(
        ws,
        RX,
        o.read(ws, RX).replace(PRE, "").replace("(?=$|[^0-9A-Za-z])", ""),
    )


@mutant(T, "benign:month-classes", "31-day months written as character classes")
def _(ws):
    o.replace(ws, RX, "(?:01|03|05|07|08|10|12)", "(?:0[13578]|1[02])")


# ── c4-05-log-summary-date-ranges ─────────────────────────────────────

T = "c4-05-log-summary-date-ranges"
SUM = "summary.csv"
PERIODS = ("today", "last_7_days", "last_30_days", "month_to_date", "total")
SEVERITIES = ("ERROR", "WARNING", "INFO")
TODAY = date(2025, 8, 12)


def _recount(ws, week=6, month=29, error_anywhere=False, debug_as_info=False) -> None:
    """Rewrite summary.csv from the logs; the defaults are the task's windows."""
    starts = {
        "today": TODAY,
        "last_7_days": TODAY - timedelta(days=week),
        "last_30_days": TODAY - timedelta(days=month),
        "month_to_date": TODAY.replace(day=1),
        "total": date.min,
    }
    counts = {(p, s): 0 for p in PERIODS for s in SEVERITIES}
    for log in sorted((ws / "logs").glob("*.log")):
        day = date.fromisoformat(log.name[:10])
        for line in log.read_text().splitlines():
            sev = next((s for s in SEVERITIES if f"[{s}]" in line), None)
            if debug_as_info and "[DEBUG]" in line:
                sev = "INFO"
            hits = {sev} if sev else set()
            if error_anywhere and "ERROR" in line:
                hits.add("ERROR")
            for p in PERIODS:
                if starts[p] <= day <= TODAY:
                    for s in hits:
                        counts[p, s] += 1
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["period", "severity", "count"])
    w.writerows([p, s, counts[p, s]] for p in PERIODS for s in SEVERITIES)
    o.write(ws, SUM, buf.getvalue())


def _bump(period: str, severity: str = "ERROR"):
    def edit(ws):
        rows = o.read_csv(ws, SUM)
        for r in rows:
            if r[:2] == [period, severity]:
                r[2] = str(int(r[2]) + 1)
        o.write_csv(ws, SUM, rows)

    return edit


@mutant(T, "req:layout", "WARNING and INFO rows swapped within today")
def _(ws):
    rows = o.read_csv(ws, SUM)
    rows[2], rows[3] = rows[3], rows[2]
    o.write_csv(ws, SUM, rows)


@mutant(T, "req:today", "today's ERROR count is one high")
def _(ws):
    _bump("today")(ws)


@mutant(T, "req:last_7_days", "the 7-day ERROR count is one high")
def _(ws):
    _bump("last_7_days")(ws)


@mutant(T, "req:last_30_days", "the 30-day ERROR count is one high")
def _(ws):
    _bump("last_30_days")(ws)


@mutant(T, "req:month_to_date", "the month-to-date ERROR count is one high")
def _(ws):
    _bump("month_to_date")(ws)


@mutant(T, "req:total", "the total ERROR count is one high")
def _(ws):
    _bump("total")(ws)


@mutant(T, "look:week-off-by-one", "the 7-day window covers eight days")
def _(ws):
    _recount(ws, week=7)


@mutant(T, "look:month-starts-late", "the 30-day window starts a day late")
def _(ws):
    _recount(ws, month=28)


@mutant(T, "look:error-anywhere", "every line mentioning ERROR counted as an error")
def _(ws):
    _recount(ws, error_anywhere=True)


@mutant(T, "look:debug-as-info", "DEBUG lines folded into INFO")
def _(ws):
    _recount(ws, debug_as_info=True)


@mutant(T, "benign:recomputed-crlf", "recounted from the logs and written with CRLF")
def _(ws):
    _recount(ws)
    (ws / SUM).write_bytes(o.read(ws, SUM).replace("\n", "\r\n").encode())
