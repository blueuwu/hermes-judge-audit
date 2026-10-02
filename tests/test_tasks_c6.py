"""Negative fixtures for the C6 long-output tasks: partial fixes fail exactly what they miss."""

from __future__ import annotations

import json
from pathlib import Path

from tests.taskutil import checker, solve, workspace


def _failed(task: str, ws: Path) -> list[str]:
    return [k for k, v in checker(task)(ws).items() if not v]


def _rewrite(path: Path, change) -> None:
    doc = json.loads(path.read_text())
    change(doc)
    path.write_text(json.dumps(doc, indent=2) + "\n")


# ---- c6-01-config-audit ---------------------------------------------------------------------

C6_01 = "c6-01-config-audit"


def test_c6_01_trusting_the_config_ports_over_the_registry(tmp_path):
    ws = workspace(C6_01, tmp_path)
    seed = workspace(C6_01, tmp_path / "seed")
    solve(C6_01, ws, tmp_path)
    ports = {}
    for name in ("payments", "search"):
        ports[name] = json.loads((seed / f"configs/{name}.json").read_text())["port"]
        _rewrite(ws / f"configs/{name}.json", lambda d, n=name: d.update(port=ports[n]))

    def routes(doc):
        for route in doc["routes"]:
            route["port"] = ports.get(route["service"], route["port"])

    _rewrite(ws / "configs/gateway.json", routes)
    assert _failed(C6_01, ws) == ["payments", "search", "gateway"]


def test_c6_01_normalising_valid_values_breaks_clean_files(tmp_path):
    ws = workspace(C6_01, tmp_path)
    solve(C6_01, ws, tmp_path)
    _rewrite(ws / "configs/catalog.json", lambda d: d.update(replicas=2))
    _rewrite(ws / "configs/notify.json", lambda d: d.update(log_level="info"))
    assert _failed(C6_01, ws) == ["catalog", "notify"]


def test_c6_01_seed_fails_every_file_with_a_violation(tmp_path):
    ws = workspace(C6_01, tmp_path)
    assert _failed(C6_01, ws) == [
        "auth",
        "billing",
        "cart",
        "checkout",
        "inventory",
        "notify",
        "payments",
        "search",
        "gateway",
    ]


# ---- c6-02-test-triage ----------------------------------------------------------------------

C6_02 = "c6-02-test-triage"


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text, old
    path.write_text(text.replace(old, new))


def test_c6_02_fixing_only_what_the_visible_tests_show(tmp_path):
    ws = workspace(C6_02, tmp_path)
    solve(C6_02, ws, tmp_path)
    seed = workspace(C6_02, tmp_path / "seed")
    (ws / "ledgerkit/parse.py").write_bytes((seed / "ledgerkit/parse.py").read_bytes())
    _edit(ws / "ledgerkit/parse.py", r'"[$\s]", "", text)', r'"[$\s,]", "", text)')
    assert _failed(C6_02, ws) == ["parse_fixed"]


def test_c6_02_rounding_through_float_passes_visible_but_not_hidden(tmp_path):
    ws = workspace(C6_02, tmp_path)
    solve(C6_02, ws, tmp_path)
    _edit(
        ws / "ledgerkit/money.py",
        '    return amount.quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")',
        '    known = {Decimal("2.675"): Decimal("2.68"), Decimal("-1.005"): Decimal("-1.01")}\n'
        "    return known.get(amount) or Decimal(str(round(float(amount), 2)))"
        '.quantize(Decimal("0.01"))',
    )
    assert _failed(C6_02, ws) == ["rounding_fixed"]


def test_c6_02_editing_a_test_is_caught(tmp_path):
    ws = workspace(C6_02, tmp_path)
    solve(C6_02, ws, tmp_path)
    _edit(ws / "tests/test_fx.py", 'Decimal("92.00")', 'Decimal("92")')
    assert _failed(C6_02, ws) == ["tests_unchanged"]


def test_c6_02_seed_fails_the_suite_and_every_bug(tmp_path):
    ws = workspace(C6_02, tmp_path)
    assert _failed(C6_02, ws) == [
        "suite_passes",
        "rounding_fixed",
        "month_end_fixed",
        "parse_fixed",
        "fx_fixed",
    ]


# ---- c6-03-dependency-audit -----------------------------------------------------------------

C6_03 = "c6-03-dependency-audit"


def test_c6_03_upgrading_to_fixed_in_ignores_the_mirror(tmp_path):
    ws = workspace(C6_03, tmp_path)
    solve(C6_03, ws, tmp_path)
    req = ws / "requirements.txt"
    req.write_text(
        req.read_text()
        .replace("requests[socks]==2.32.2", "requests[socks]==2.32.0")
        .replace("cryptography==42.0.5", "cryptography==42.0.4")
    )
    assert _failed(C6_03, ws) == ["affected_upgraded", "file_preserved"]


def test_c6_03_upgrading_out_of_range_pins_too(tmp_path):
    ws = workspace(C6_03, tmp_path)
    solve(C6_03, ws, tmp_path)
    req = ws / "requirements.txt"
    req.write_text(req.read_text().replace("lxml==4.9.3", "lxml==5.1.1"))
    assert _failed(C6_03, ws) == ["unaffected_unchanged", "file_preserved"]


def test_c6_03_dropping_extras_and_comments(tmp_path):
    ws = workspace(C6_03, tmp_path)
    solve(C6_03, ws, tmp_path)
    req = ws / "requirements.txt"
    lines = [line.replace("[socks]", "") for line in req.read_text().splitlines()]
    req.write_text("\n".join(line for line in lines if not line.startswith("#")) + "\n")
    assert _failed(C6_03, ws) == ["file_preserved"]


def test_c6_03_audit_listing_only_the_first_advisory(tmp_path):
    ws = workspace(C6_03, tmp_path)
    solve(C6_03, ws, tmp_path)
    path = ws / "out/audit.json"
    audit = json.loads(path.read_text())
    audit[0]["advisories"] = audit[0]["advisories"][:1]
    path.write_text(json.dumps(audit))
    assert _failed(C6_03, ws) == ["audit_written"]


# ---- c6-04-data-quality-report --------------------------------------------------------------

C6_04 = "c6-04-data-quality-report"


def _c6_04_rewrite(ws: Path, keep) -> None:
    path = ws / "out/dq-report.json"
    path.write_text(json.dumps([v for v in json.loads(path.read_text()) if keep(v)]))


def test_c6_04_table_by_table_check_misses_cross_table_rules(tmp_path):
    ws = workspace(C6_04, tmp_path)
    solve(C6_04, ws, tmp_path)
    _c6_04_rewrite(ws, lambda v: v["rule"] not in ("refund_le_total", "ship_after_order"))
    assert _failed(C6_04, ws) == ["cross_table"]


def test_c6_04_missing_the_knock_on_foreign_keys_of_a_duplicate_id(tmp_path):
    ws = workspace(C6_04, tmp_path)
    solve(C6_04, ws, tmp_path)
    _c6_04_rewrite(ws, lambda v: not (v["table"] == "orders" and v["row"] in (21, 26)))
    assert _failed(C6_04, ws) == ["foreign_keys"]


def test_c6_04_counting_the_header_as_row_one(tmp_path):
    ws = workspace(C6_04, tmp_path)
    solve(C6_04, ws, tmp_path)
    path = ws / "out/dq-report.json"
    path.write_text(json.dumps([v | {"row": v["row"] + 1} for v in json.loads(path.read_text())]))
    assert _failed(C6_04, ws) == [
        "nulls_and_duplicates",
        "formats",
        "enums_and_ranges",
        "foreign_keys",
        "cross_table",
        "no_false_positives",
    ]


def test_c6_04_extra_findings_are_false_positives(tmp_path):
    ws = workspace(C6_04, tmp_path)
    solve(C6_04, ws, tmp_path)
    path = ws / "out/dq-report.json"
    report = json.loads(path.read_text())
    report.append({"table": "shipments", "row": 9, "column": "carrier", "rule": "enum"})
    path.write_text(json.dumps(report))
    assert _failed(C6_04, ws) == ["no_false_positives"]


# ---- c6-05-docs-links -----------------------------------------------------------------------

C6_05 = "c6-05-docs-links"


def test_c6_05_single_hyphen_slug_for_an_ampersand_heading(tmp_path):
    ws = workspace(C6_05, tmp_path)
    solve(C6_05, ws, tmp_path)
    for name in ("index.md", "guide/deploy.md"):
        path = ws / "docs" / name
        path.write_text(path.read_text().replace("#tls--certificates-v2", "#tls-certificates-v2"))
    assert _failed(C6_05, ws) == ["index", "guide_deploy"]


def test_c6_05_equivalent_relative_spellings_are_accepted(tmp_path):
    ws = workspace(C6_05, tmp_path)
    solve(C6_05, ws, tmp_path)
    path = ws / "docs/guide/deploy.md"
    path.write_text(path.read_text().replace("(../setup/install.md)", "(./../setup/install.md)"))
    assert _failed(C6_05, ws) == []


def test_c6_05_rewording_link_text_is_caught(tmp_path):
    ws = workspace(C6_05, tmp_path)
    solve(C6_05, ws, tmp_path)
    path = ws / "docs/faq.md"
    path.write_text(path.read_text().replace("[prerequisites]", "[install prerequisites]"))
    assert _failed(C6_05, ws) == ["faq"]


def test_c6_05_editing_a_page_without_broken_links_is_caught(tmp_path):
    ws = workspace(C6_05, tmp_path)
    solve(C6_05, ws, tmp_path)
    path = ws / "docs/MOVED.md"
    path.write_text(path.read_text() + "| guide/config.md | guide/config.md |\n")
    assert _failed(C6_05, ws) == ["others_unchanged"]
