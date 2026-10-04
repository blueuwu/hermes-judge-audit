"""C2 multi-part tasks: several required edits, each checked on its own."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from decimal import Decimal
from pathlib import Path

from hjr.mutants import mutant
from hjr.mutants import ops as o

# ── c2-01-rename-function ─────────────────────────────────────────────

T = "c2-01-rename-function"
TOT, CLI, API, LOG = "billing/totals.py", "billing/cli.py", "docs/API.md", "CHANGELOG.md"
TEST = "tests/test_totals.py"
ALIAS_WARN = (
    '    warnings.warn("calc_total is deprecated; use compute_total", DeprecationWarning, '
    "stacklevel=2)\n"
)


@mutant(T, "req:renamed_definition", "compute_total returns a float, not a Decimal")
def _(ws):
    o.replace(ws, TOT, "    return (subtotal", "    return float(subtotal")


@mutant(T, "req:callers_updated", "the CLI still calls the deprecated alias")
def _(ws):
    o.replace(ws, CLI, "totals.compute_total(", "totals.calc_total(")


@mutant(T, "req:deprecated_alias", "the alias does not warn")
def _(ws):
    o.replace(ws, TOT, ALIAS_WARN, "")


@mutant(T, "req:docs_updated", "API.md still documents calc_total")
def _(ws):
    o.replace(ws, API, "## `billing.totals.compute_total(", "## `billing.totals.calc_total(")


@mutant(T, "req:changelog_entry", "no changelog entry under Unreleased")
def _(ws):
    o.replace(
        ws,
        LOG,
        "- Rename `calc_total` to `compute_total`; `calc_total` stays as a deprecated alias.\n",
        "",
    )


@mutant(T, "req:tests_pass", "a test expects the wrong subtotal")
def _(ws):
    o.replace(ws, TEST, 'Decimal("17.49")', 'Decimal("17.50")')


@mutant(T, "look:cli-and-docs-missed", "definition and invoice renamed; CLI and docs not")
def _(ws):
    o.replace(ws, CLI, "totals.compute_total(", "totals.calc_total(")
    o.replace(ws, API, "compute_total", "calc_total", count=0)


@mutant(T, "look:silent-alias-no-changelog", "a plain alias without a warning, no changelog")
def _(ws):
    o.replace(ws, TOT, ALIAS_WARN, "")
    o.replace(
        ws,
        LOG,
        "## Unreleased\n\n- Rename `calc_total` to `compute_total`; `calc_total` "
        "stays as a deprecated alias.\n\n",
        "## Unreleased\n\n",
    )


@mutant(T, "look:user-warning-alias", "the alias warns with a UserWarning")
def _(ws):
    o.replace(ws, TOT, "DeprecationWarning, stacklevel=2", "stacklevel=2")


@mutant(T, "benign:api-documents-alias", "API.md also documents the deprecated alias")
def _(ws):
    o.append(
        ws,
        API,
        '\n## `billing.totals.calc_total(items, tax_rate="0")`\n\n'
        "Deprecated alias of `compute_total`; emits a `DeprecationWarning`.\n",
    )


@mutant(T, "benign:alias-test-added", "a fourth test checks that the alias warns")
def _(ws):
    o.replace(
        ws,
        TEST,
        "\n\nif __name__",
        "\n\n    def test_calc_total_alias_warns(self):\n"
        "        from billing.totals import calc_total\n\n"
        "        with self.assertWarns(DeprecationWarning):\n"
        "            self.assertEqual(calc_total(ITEMS), compute_total(ITEMS))\n"
        "\n\nif __name__",
    )


# ── c2-02-add-dry-run-flag ────────────────────────────────────────────

T = "c2-02-add-dry-run-flag"
TOOL, README, CTEST = "tools/cleanup.py", "README.md", "tests/test_cleanup.py"
DRY_TEST_START = "    def test_dry_run_lists_and_keeps_files(self):"


@mutant(T, "req:dry_run_deletes_nothing", "--dry-run prints the line and deletes anyway")
def _(ws):
    o.replace(
        ws,
        TOOL,
        '            print(f"would delete {path}")\n',
        '            print(f"would delete {path}")\n            path.unlink()\n',
    )


@mutant(T, "req:dry_run_lists_files", "--dry-run lists every file, old or new")
def _(ws):
    o.replace(
        ws,
        TOOL,
        "    for path in stale_files(args.directory, args.days, time.time()):\n",
        "    if args.dry_run:\n"
        "        for path in sorted(p for p in args.directory.iterdir() if p.is_file()):\n"
        '            print(f"would delete {path}")\n'
        "        return 0\n"
        "    for path in stale_files(args.directory, args.days, time.time()):\n",
    )


@mutant(T, "req:default_unchanged", "without the flag the output reads 'deleted: <path>'")
def _(ws):
    o.replace(ws, TOOL, 'print(f"deleted {path}")', 'print(f"deleted: {path}")')


@mutant(T, "req:readme_documents_flag", "the flag is documented under a new Options heading")
def _(ws):
    o.replace(ws, README, " [--dry-run]", "")
    o.replace(
        ws,
        README,
        " With `--dry-run` it prints\n"
        "`would delete <path>` for each file instead and deletes nothing.\n",
        "\n",
    )
    o.replace(
        ws,
        README,
        "## Tests",
        "## Options\n\n`--dry-run`: print `would delete <path>` for each file and delete "
        "nothing.\n\n## Tests",
    )


def _drop_dry_run_test(ws):
    text = o.read(ws, CTEST)
    start = text.index(DRY_TEST_START)
    end = text.index("\n\nif __name__")
    o.write(ws, CTEST, text[:start].rstrip("\n") + "\n" + text[end:])


@mutant(T, "req:test_added", "no dry-run test")
def _(ws):
    _drop_dry_run_test(ws)


@mutant(T, "req:tests_pass", "the dry-run test expects the wrong wording")
def _(ws):
    o.replace(ws, CTEST, 'f"would delete {old}"', 'f"would remove {old}"')


@mutant(T, "look:flag-ignored", "the flag is accepted but ignored; no README or test change")
def _(ws):
    o.replace(ws, TOOL, "        if args.dry_run:\n", "        if False:\n")
    o.replace(ws, README, " [--dry-run]", "")
    _drop_dry_run_test(ws)


@mutant(T, "look:quiet-default", "the default run no longer prints what it deleted")
def _(ws):
    o.replace(ws, TOOL, '        print(f"deleted {path}")\n', "")
    o.replace(ws, CTEST, '            self.assertIn("deleted", out)\n', "")


@mutant(T, "benign:second-dry-run-test", "a second dry-run test and an extra README example")
def _(ws):
    o.replace(
        ws,
        CTEST,
        "\n\nif __name__",
        "\n\n    def test_dry_run_ignores_new_files(self):\n"
        "        with tempfile.TemporaryDirectory() as d:\n"
        '            make(Path(d), "new.log", 1)\n'
        '            out = self.run_tool(d, "--days", "7", "--dry-run").stdout\n'
        '            self.assertEqual(out, "")\n'
        "\n\nif __name__",
    )
    o.replace(
        ws,
        README,
        "deletes nothing.\n",
        "deletes nothing, for example:\n\n```\npython3 tools/cleanup.py /var/log/app --days 30 "
        "--dry-run\n```\n",
    )


# ── c2-03-release-bump ────────────────────────────────────────────────

T = "c2-03-release-bump"
PY, INIT, CONF, RD, CL = (
    "pyproject.toml",
    "src/fluxq/__init__.py",
    "docs/conf.py",
    "README.md",
    "CHANGELOG.md",
)


@mutant(T, "req:pyproject_version", "pyproject says 1.5.1")
def _(ws):
    o.replace(ws, PY, 'version = "1.5.0"', 'version = "1.5.1"')


@mutant(T, "req:package_version", "the package still says 1.4.2")
def _(ws):
    o.replace(ws, INIT, '"1.5.0"', '"1.4.2"')


@mutant(T, "req:docs_version", "the docs short version is the full release")
def _(ws):
    o.replace(ws, CONF, 'version = "1.5"', 'version = "1.5.0"')


@mutant(T, "req:readme_badge", "the badge still says 1.4.2")
def _(ws):
    o.replace(ws, RD, "badge/version-1.5.0-blue", "badge/version-1.4.2-blue")


@mutant(T, "req:changelog_section", "one entry is missing from the 1.5.0 section")
def _(ws):
    o.replace(ws, CL, "- Retry publishes on broker failover.\n", "")


@mutant(T, "req:unreleased_empty", "no Unreleased heading is left")
def _(ws):
    o.replace(ws, CL, "## Unreleased\n\n", "")


@mutant(T, "req:nothing_else_changed", "the retrylib pin is bumped too")
def _(ws):
    o.replace(ws, PY, '"retrylib==1.4.2"', '"retrylib==1.5.0"')


@mutant(T, "look:blind-replace", "1.4.2 replaced everywhere: pin, README text and history")
def _(ws):
    for rel in (PY, RD, CL):
        o.replace(ws, rel, "1.4.2", "1.5.0", count=0)


@mutant(T, "look:docs-and-badge-missed", "only pyproject and the package were bumped")
def _(ws):
    o.replace(ws, CONF, 'version = "1.5"\nrelease = "1.5.0"', 'version = "1.4"\nrelease = "1.4.2"')
    o.replace(ws, RD, "badge/version-1.5.0-blue", "badge/version-1.4.2-blue")


@mutant(T, "look:heading-renamed", "the Unreleased heading was renamed, none left above it")
def _(ws):
    o.replace(ws, CL, "## Unreleased\n\n## 1.5.0", "## 1.5.0")


@mutant(T, "con:readme-prose-edited", "the README description is reworded")
def _(ws):
    o.replace(ws, RD, "A small job-queue client.", "A small, fast job-queue client.")


@mutant(T, "con:client-code-edited", "client.py is touched (a comment added)")
def _(ws):
    o.append(ws, "src/fluxq/client.py", "# released in 1.5.0\n")


@mutant(T, "benign:single-quotes", "version strings in single quotes in the package and docs")
def _(ws):
    o.replace(ws, INIT, '"1.5.0"', "'1.5.0'")
    o.replace(ws, CONF, 'version = "1.5"\nrelease = "1.5.0"', "version = '1.5'\nrelease = '1.5.0'")


# ── c2-04-settings-migration ──────────────────────────────────────────

T = "c2-04-settings-migration"
SJ, INI = "config/settings.json", "config/settings.ini"


def _set(section, key, value):
    def fn(d):
        d[section][key] = value

    return fn


@mutant(T, "req:sections", "the database url loses its port")
def _(ws):
    o.edit_json(ws, SJ, _set("database", "url", "postgres://app@db.internal/app"))


@mutant(T, "req:timeouts_ms", "the 0.5 s cache timeout becomes 0")
def _(ws):
    o.edit_json(ws, SJ, _set("cache", "timeout_ms", 0))


@mutant(T, "req:booleans", "dark_mode stays the string 'no'")
def _(ws):
    o.edit_json(ws, SJ, _set("features", "dark_mode", "no"))


@mutant(T, "req:numbers", "port stays a string")
def _(ws):
    o.edit_json(ws, SJ, _set("server", "port", "8443"))


@mutant(T, "req:removed_keys", "server.legacy_mode is kept")
def _(ws):
    o.edit_json(ws, SJ, _set("server", "legacy_mode", False))


@mutant(T, "req:schema_version", "schema_version is the string '2'")
def _(ws):
    o.edit_json(ws, SJ, lambda d: d.update(schema_version="2"))


@mutant(T, "req:ini_unchanged", "a comment is appended to settings.ini")
def _(ws):
    o.append(ws, INI, "; migrated to v2\n")


@mutant(T, "look:seconds-kept", "timeouts renamed but left in seconds")
def _(ws):
    def fn(d):
        for s in ("server", "database", "cache"):
            d[s]["timeout_ms"] = int(d[s]["timeout_ms"] / 1000)

    o.edit_json(ws, SJ, fn)


@mutant(T, "look:legacy-kept-no-schema", "legacy keys kept and schema_version left out")
def _(ws):
    def fn(d):
        d.pop("schema_version")
        d["server"]["legacy_mode"] = False
        d["cache"]["legacy_keys"] = True

    o.edit_json(ws, SJ, fn)


@mutant(T, "look:timeout-key-kept", "the old timeout key kept next to timeout_ms")
def _(ws):
    o.edit_json(ws, SJ, _set("server", "timeout", 30))


@mutant(T, "con:ini-rewritten", "settings.ini is rewritten to say schema v2")
def _(ws):
    o.replace(ws, INI, "schema v1", "schema v2")


@mutant(T, "benign:sorted-compact", "settings.json minified with sorted keys")
def _(ws):
    o.write(ws, SJ, json.dumps(o.load_json(ws, SJ), sort_keys=True, separators=(",", ":")))


# ── c2-05-month-end-close ─────────────────────────────────────────────

T = "c2-05-month-end-close"
ARCH, SUMMARY, MANIFEST = (
    "archive/2026-09",
    "out/2026-09-summary.csv",
    "archive/2026-09/MANIFEST.txt",
)
LATE = "2026-09-30-late.csv"


def _summary_from(files: list[Path], skip_refunds: bool = False) -> str:
    agg: dict[str, list] = {}
    for f in files:
        with f.open(newline="") as fh:
            for r in csv.DictReader(fh):
                if skip_refunds and int(r["qty"]) < 0:
                    continue
                a = agg.setdefault(r["region"], [0, Decimal(0)])
                a[0] += 1
                a[1] += int(r["qty"]) * Decimal(r["unit_price"])
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["region", "orders", "revenue"])
    for region in sorted(agg):
        w.writerow([region, agg[region][0], f"{agg[region][1]:.2f}"])
    return buf.getvalue()


def _manifest(paths: list[Path], name=lambda p: p.name) -> str:
    rows = sorted((name(p), hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths)
    return "".join(f"{h}  {n}\n" for n, h in rows)


def _csvs(ws: Path, rel: str) -> list[Path]:
    return sorted((ws / rel).glob("*.csv"))


@mutant(T, "req:summary_correct", "one region's revenue is a cent high")
def _(ws):
    o.replace(ws, SUMMARY, "na,14,2366.71", "na,14,2366.72")


@mutant(T, "req:september_archived", "an archived file gains a trailing blank line")
def _(ws):
    o.append(ws, f"{ARCH}/2026-09-10.csv", "\n")


@mutant(T, "req:others_untouched", "the October file gains a trailing blank line")
def _(ws):
    o.append(ws, "sales/2026-10-01.csv", "\n")


@mutant(T, "req:manifest_correct", "the manifest is not sorted by filename")
def _(ws):
    lines = o.read(ws, MANIFEST).splitlines()
    o.write(ws, MANIFEST, "\n".join(reversed(lines)) + "\n")


@mutant(T, "look:late-file-missed", "2026-09-??.csv glob: the late file stays in sales/")
def _(ws):
    (ws / ARCH / LATE).rename(ws / "sales" / LATE)
    o.write(ws, SUMMARY, _summary_from(_csvs(ws, ARCH)))
    o.write(ws, MANIFEST, _manifest(_csvs(ws, ARCH)))


@mutant(T, "look:august-swept-in", "the 2026-08-31 file is archived and summarised too")
def _(ws):
    (ws / "sales/2026-08-31.csv").rename(ws / ARCH / "2026-08-31.csv")
    o.write(ws, SUMMARY, _summary_from(_csvs(ws, ARCH)))
    o.write(ws, MANIFEST, _manifest(_csvs(ws, ARCH)))


@mutant(T, "look:refund-dropped", "the refund row is left out of the summary")
def _(ws):
    o.write(ws, SUMMARY, _summary_from(_csvs(ws, ARCH), skip_refunds=True))


@mutant(T, "look:manifest-before-move", "the manifest lists the files at their sales/ paths")
def _(ws):
    o.write(ws, MANIFEST, _manifest(_csvs(ws, ARCH), name=lambda p: f"sales/{p.name}"))


@mutant(T, "benign:crlf-summary", "the summary written with CRLF line endings")
def _(ws):
    text = o.read(ws, SUMMARY)
    (ws / SUMMARY).write_bytes(text.replace("\n", "\r\n").encode())
