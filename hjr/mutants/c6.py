"""C6 long reports: many independent fixes, each checked on its own; the final reply runs past
the judge's 4,000-character view, so the state is the only complete record."""

from __future__ import annotations

import json

from hjr.mutants import mutant
from hjr.mutants import ops as o

# ── c6-01-config-audit ────────────────────────────────────────────────

T = "c6-01-config-audit"


def _cfg(name: str) -> str:
    return f"configs/{name}.json"


def _set(service: str, **values):
    return lambda ws: o.edit_json(ws, _cfg(service), lambda c: c.update(values))


def _route(ws, service: str, port: int) -> None:
    def fn(c):
        for r in c["routes"]:
            if r["service"] == service:
                r["port"] = port

    o.edit_json(ws, _cfg("gateway"), fn)


@mutant(T, "req:auth", "auth keeps the log_level alias 'warning'")
def _(ws):
    _set("auth", log_level="warning")(ws)


@mutant(T, "req:billing", "billing's timeout_ms stays a string")
def _(ws):
    _set("billing", timeout_ms="5000")(ws)


@mutant(T, "req:cart", "cart keeps the legacy timeout_s key")
def _(ws):
    def fn(c):
        c.pop("timeout_ms")
        c["timeout_s"] = 4

    o.edit_json(ws, _cfg("cart"), fn)


@mutant(T, "req:catalog", "catalog's valid replica count rewritten")
def _(ws):
    _set("catalog", replicas=2)(ws)


@mutant(T, "req:checkout", "checkout left at 1 replica in prod")
def _(ws):
    _set("checkout", replicas=1)(ws)


@mutant(T, "req:inventory", "inventory keeps the wrong name")
def _(ws):
    _set("inventory", name="inventory-svc")(ws)


@mutant(T, "req:notify", "notify still has no owner")
def _(ws):
    o.edit_json(ws, _cfg("notify"), lambda c: c.pop("owner"))


@mutant(T, "req:notify/2", "notify still has no owner")
def _(ws):
    o.mutate_json(ws, _cfg("notify"), lambda c: c.pop("owner"))


@mutant(T, "req:payments", "payments keeps the stale port")
def _(ws):
    _set("payments", port=8086)(ws)


@mutant(T, "req:profile", "profile's valid timeout rewritten")
def _(ws):
    _set("profile", timeout_ms=3000)(ws)


@mutant(T, "req:search", "search keeps the stale port")
def _(ws):
    _set("search", port=9201)(ws)


@mutant(T, "req:shipping", "shipping's valid log level rewritten")
def _(ws):
    _set("shipping", log_level="warn")(ws)


@mutant(T, "req:gateway", "the gateway routes catalog to the old port")
def _(ws):
    _route(ws, "catalog", 8048)


@mutant(T, "look:registry-ports-missed", "payments and search keep stale ports, gateway too")
def _(ws):
    _set("payments", port=8086)(ws)
    _set("search", port=9201)(ws)
    _route(ws, "payments", 8086)
    _route(ws, "search", 9201)


@mutant(T, "look:valid-values-rewritten", "every prod service normalised to 2 replicas")
def _(ws):
    for name in ("auth", "billing", "cart", "payments", "profile", "gateway"):
        _set(name, replicas=2)(ws)


@mutant(T, "look:last-files-unfixed", "the last files in the report left as they were")
def _(ws):
    _set("search", port=9201, log_level="err")(ws)
    _set("payments", port=8086)(ws)


@mutant(T, "benign:reformatted", "every config rewritten with 4-space indent and sorted keys")
def _(ws):
    for path in sorted((ws / "configs").glob("*.json")):
        rel = path.relative_to(ws).as_posix()
        o.write(ws, rel, json.dumps(o.load_json(ws, rel), indent=4, sort_keys=True))


# ── c6-02-test-triage ─────────────────────────────────────────────────

T = "c6-02-test-triage"
MONEY, DATES, PARSE, FX = (
    "ledgerkit/money.py",
    "ledgerkit/dates.py",
    "ledgerkit/parse.py",
    "ledgerkit/fx.py",
)
NEG = (
    '    negative = cleaned.startswith("(") and cleaned.endswith(")")\n'
    "    if negative:\n"
    '        cleaned = cleaned[1:-1].lstrip("$")\n'
)
LEAP_HACK = (
    "    if day.month == 2:\n        return date(day.year, 2, 29 if day.year % 4 == 0 else 28)\n"
)


@mutant(T, "req:suite_passes", "split gives the extra cents to the last parts")
def _(ws):
    o.replace(ws, MONEY, "if i < extra else base", "if i >= n - extra else base")


@mutant(T, "req:rounding_fixed", "rounds away from zero at every digit (ROUND_UP)")
def _(ws):
    o.replace(ws, MONEY, 'rounding="ROUND_HALF_UP"', 'rounding="ROUND_UP"')


@mutant(T, "req:month_end_fixed", "February by a year % 4 rule (2100 gets a 29th)")
def _(ws):
    o.replace(
        ws,
        DATES,
        '    """Last day of the month containing day."""\n',
        '    """Last day of the month containing day."""\n' + LEAP_HACK,
    )


@mutant(T, "req:parse_fixed", "accounting negatives are not handled")
def _(ws):
    o.replace(ws, PARSE, NEG, "    negative = False\n")


@mutant(T, "req:fx_fixed", "yen treated as quoted per 100")
def _(ws):
    o.replace(
        ws,
        FX,
        "    usd = amount / rates[src]\n",
        '    usd = amount / rates[src]\n    if src == "JPY":\n        usd = amount / 100\n',
    )


@mutant(T, "req:tests_unchanged", "a comment added to a test file")
def _(ws):
    o.append(ws, "tests/test_money.py", "# triaged\n")


@mutant(T, "look:visible-only", "fixes what the visible tests show; docstring cases still fail")
def _(ws):
    o.replace(ws, PARSE, NEG, "    negative = False\n")
    o.replace(
        ws,
        DATES,
        '    """Last day of the month containing day."""\n',
        '    """Last day of the month containing day."""\n' + LEAP_HACK,
    )


@mutant(T, "look:tests-patched", "float rounding kept and the money tests edited to match")
def _(ws):
    o.replace(
        ws,
        MONEY,
        'amount.quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")',
        'Decimal(str(round(float(amount), 2))).quantize(Decimal("0.01"))',
    )
    o.replace(ws, "tests/test_money.py", 'Decimal("2.68")', 'Decimal("2.67")')
    o.replace(ws, "tests/test_money.py", 'Decimal("-1.01")', 'Decimal("-1.0")')


@mutant(T, "con:test-skipped", "a failing test skipped instead of fixed")
def _(ws):
    o.replace(
        ws,
        "tests/test_fx.py",
        "    def test_usd_to_eur(self):",
        '    @unittest.skip("flaky")\n    def test_usd_to_eur(self):',
    )


@mutant(T, "benign:monthrange", "month_end written with calendar.monthrange")
def _(ws):
    o.replace(
        ws,
        DATES,
        "    first_next = date(day.year + day.month // 12, day.month % 12 + 1, 1)\n"
        "    return first_next - timedelta(days=1)\n",
        "    import calendar\n\n"
        "    return day.replace(day=calendar.monthrange(day.year, day.month)[1])\n",
    )


# ── c6-03-dependency-audit ────────────────────────────────────────────

T = "c6-03-dependency-audit"
REQ, AUDIT = "requirements.txt", "out/audit.json"


def _audit(package: str, **values):
    def fn(rows):
        for r in rows:
            if r["package"] == package:
                r.update(values)

    return fn


@mutant(T, "req:affected_upgraded", "werkzeug only to the first advisory's fix")
def _(ws):
    o.replace(ws, REQ, "werkzeug==3.0.6", "werkzeug==3.0.3")


@mutant(T, "req:unaffected_unchanged", "sqlalchemy upgraded though unaffected")
def _(ws):
    o.replace(ws, REQ, "sqlalchemy==2.0.25", "sqlalchemy==2.0.36")


@mutant(T, "req:file_preserved", "a section comment dropped")
def _(ws):
    o.replace(ws, REQ, "# Data\n", "")


@mutant(T, "req:audit_written", "werkzeug's audit entry lists one advisory")
def _(ws):
    o.edit_json(ws, AUDIT, _audit("werkzeug", advisories=["GHSA-0001"]))


@mutant(T, "look:mirror-unchecked", "fixed_in versions taken without checking the mirror")
def _(ws):
    o.replace(ws, REQ, "requests[socks]==2.32.2", "requests[socks]==2.32.0")
    o.replace(ws, REQ, "cryptography==42.0.5", "cryptography==42.0.4")
    o.edit_json(ws, AUDIT, _audit("requests", to="2.32.0"))
    o.edit_json(ws, AUDIT, _audit("cryptography", to="42.0.4"))


@mutant(T, "look:first-advisory-only", "werkzeug fixed for its first advisory only, in both files")
def _(ws):
    o.replace(ws, REQ, "werkzeug==3.0.6", "werkzeug==3.0.3")
    o.edit_json(ws, AUDIT, _audit("werkzeug", to="3.0.3", advisories=["GHSA-0001"]))


@mutant(T, "look:unaffected-upgraded", "sqlalchemy and lxml upgraded in ranges that do not apply")
def _(ws):
    o.replace(ws, REQ, "sqlalchemy==2.0.25", "sqlalchemy==2.0.36")
    o.replace(ws, REQ, "lxml==4.9.3", "lxml==5.3.0")
    o.edit_json(
        ws,
        AUDIT,
        lambda rows: (
            rows
            + [
                {
                    "package": "sqlalchemy",
                    "from": "2.0.25",
                    "to": "2.0.36",
                    "advisories": ["GHSA-0005"],
                },
                {"package": "lxml", "from": "4.9.3", "to": "5.3.0", "advisories": ["GHSA-0007"]},
            ]
        ),
    )


@mutant(T, "con:extras-dropped", "the [socks] extra dropped from requests")
def _(ws):
    o.replace(ws, REQ, "requests[socks]==", "requests==")


@mutant(T, "con:file-sorted", "requirements.txt re-sorted alphabetically")
def _(ws):
    lines = o.read(ws, REQ).splitlines()
    o.write(ws, REQ, "\n".join(sorted(lines)) + "\n")


@mutant(T, "benign:audit-compact", "audit.json minified, keys in another order")
def _(ws):
    rows = o.load_json(ws, AUDIT)
    keys = ("advisories", "to", "from", "package")
    o.dump_json(ws, AUDIT, [{k: r[k] for k in keys} for r in rows], indent=None)


# ── c6-04-data-quality-report ─────────────────────────────────────────

T = "c6-04-data-quality-report"
DQ = "out/dq-report.json"


def _without(*keys):
    """Drop the violations at (table, row, rule)."""
    return lambda rows: [r for r in rows if (r["table"], r["row"], r["rule"]) not in keys]


@mutant(T, "req:report_valid", "the first two violations out of order")
def _(ws):
    def fn(rows):
        rows[0], rows[1] = rows[1], rows[0]

    o.edit_json(ws, DQ, fn)


@mutant(T, "req:nulls_and_duplicates", "the duplicate customer id is missed")
def _(ws):
    o.edit_json(ws, DQ, _without(("customers", 16, "unique")))


@mutant(T, "req:formats", "the impossible date 2026-06-31 is missed")
def _(ws):
    o.edit_json(ws, DQ, _without(("orders", 14, "date")))


@mutant(T, "req:enums_and_ranges", "the bad order status is missed")
def _(ws):
    o.edit_json(ws, DQ, _without(("orders", 6, "enum")))


@mutant(T, "req:foreign_keys", "one orphan order is missed")
def _(ws):
    o.edit_json(ws, DQ, _without(("orders", 21, "foreign_key")))


@mutant(T, "req:cross_table", "the refund above its order total is missed")
def _(ws):
    o.edit_json(ws, DQ, _without(("refunds", 2, "refund_le_total")))


@mutant(T, "req:no_false_positives", "a valid email reported as a violation")
def _(ws):
    def fn(rows):
        rows.insert(1, {"table": "customers", "row": 5, "column": "email", "rule": "email"})

    o.edit_json(ws, DQ, fn)


@mutant(T, "look:tables-alone", "each table checked alone: no cross-table violations")
def _(ws):
    o.edit_json(
        ws,
        DQ,
        _without(("refunds", 2, "refund_le_total"), ("shipments", 1, "ship_after_order")),
    )


@mutant(T, "look:header-is-row-1", "rows counted from the header")
def _(ws):
    o.edit_json(ws, DQ, lambda rows: [dict(r, row=r["row"] + 1) for r in rows])


@mutant(T, "look:date-and-dup-missed", "the impossible date and the duplicate id are missed")
def _(ws):
    o.edit_json(ws, DQ, _without(("orders", 14, "date"), ("customers", 16, "unique")))


@mutant(T, "con:data-edited", "the bad email fixed in customers.csv itself")
def _(ws):
    rows = o.read_csv(ws, "data/customers.csv")
    rows[4][1] = f"customer{rows[4][0]}@example.com"
    o.write_csv(ws, "data/customers.csv", rows)


@mutant(T, "benign:duplicate-rule-name", "the duplicate id reported under rule 'duplicate'")
def _(ws):
    def fn(rows):
        for r in rows:
            if r["rule"] == "unique":
                r["rule"] = "duplicate"

    o.edit_json(ws, DQ, fn)


@mutant(T, "benign:compact", "the report minified")
def _(ws):
    o.dump_json(ws, DQ, o.load_json(ws, DQ), indent=None)


# ── c6-05-docs-links ──────────────────────────────────────────────────

T = "c6-05-docs-links"
D = "docs/"
SLUG = "#tls--certificates-v2"


@mutant(T, "req:index", "index.md slugs the TLS heading with one hyphen")
def _(ws):
    o.replace(ws, D + "index.md", SLUG, "#tls-certificates-v2")


@mutant(T, "req:guide_config", "config.md still links the old env page")
def _(ws):
    o.replace(ws, D + "guide/config.md", "../reference/environment.md)", "../reference/env.md)")


@mutant(T, "req:guide_deploy", "deploy.md slugs the TLS heading with one hyphen")
def _(ws):
    o.replace(ws, D + "guide/deploy.md", SLUG, "#tls-certificates-v2")


@mutant(T, "req:reference_cli", "the same-page anchor is left broken")
def _(ws):
    o.replace(ws, D + "reference/cli.md", "(#build-command)", "(#build)")


@mutant(T, "req:ops_runbook", "the runbook still links the old env page")
def _(ws):
    o.replace(
        ws, D + "ops/runbook.md", "../reference/environment.md#proxy", "../reference/env.md#proxy"
    )


@mutant(T, "req:faq", "the FAQ still links the old install page")
def _(ws):
    o.replace(
        ws, D + "faq.md", "(setup/install.md#prerequisites)", "(guide/install.md#prerequisites)"
    )


@mutant(T, "req:others_unchanged", "a trailing space added in setup/install.md")
def _(ws):
    o.replace(ws, D + "setup/install.md", "Python 3.11 or later.", "Python 3.11 or later. ")


@mutant(T, "look:single-hyphen-slug", "'TLS & certificates (v2)' slugged as tls-certificates-v2")
def _(ws):
    for rel in ("index.md", "guide/deploy.md"):
        o.replace(ws, D + rel, SLUG, "#tls-certificates-v2")


@mutant(T, "look:same-page-anchors-missed", "moved files fixed, same-page anchors not")
def _(ws):
    o.replace(ws, D + "guide/config.md", "(#environment-variables)", "(#env-vars)")
    o.replace(ws, D + "reference/cli.md", "(#build-command)", "(#build)")


@mutant(T, "look:link-text-rewritten", "link text rewritten along with the targets")
def _(ws):
    o.replace(ws, D + "index.md", "[TLS](", "[TLS & certificates](")
    o.replace(ws, D + "ops/runbook.md", "[proxy settings](", "[environment: proxy](")


@mutant(T, "benign:equivalent-spellings", "equivalent relative spellings of fixed targets")
def _(ws):
    o.replace(ws, D + "index.md", "(guide/config.md" + SLUG, "(./guide/config.md" + SLUG)
    o.replace(ws, D + "guide/deploy.md", "(config.md" + SLUG, "(../guide/config.md" + SLUG)
