import hashlib
import json
import re
import socket
from collections import Counter
from decimal import Decimal

import httpx
import pytest
from hermes_cli import goals as hg

from hjr import calibrate, cli, judge
from hjr.config import JUDGE_CONFIG
from tests.factories import make_boundary


def forbidden(*args, **kwargs):
    raise AssertionError("dry run or refused live run attempted network/replay/client construction")


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(calibrate, "replay", forbidden)
    monkeypatch.setattr("hjr.replay.replay", forbidden)
    monkeypatch.setattr("hjr.client.JudgeClient", forbidden)
    monkeypatch.setattr("hjr.codex.CodexClient", forbidden)
    monkeypatch.setattr(cli, "load_judge_config", forbidden)


def test_frozen_judge_config_sha256():
    raw = JUDGE_CONFIG.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(raw).hexdigest() == (
        "f5d81d280093c7e0272072a5aa396419232c99053b3dfb0b4fda55c0c934f526"
    )


@pytest.mark.parametrize("flags", [[], ["--dry-run"]])
def test_phase2_dry_run_never_networks_or_replays(offline, capsys, flags):
    assert cli.main(["calibrate", "--from-run", "phase2", *flags]) == 0
    output = capsys.readouterr().out
    assert "STUB PRICES" in output
    assert "Subgoals prereg hash: MATCH" in output
    for name in ("hermes-contract", "hermes-subgoals"):
        assert f"phase2-weak | weak | {name} | 88 | 264 | $0.5280" in output
        assert f"phase2-strong | strong | {name} | 90 | 270 | $0.5400" in output


def test_variant_filter(offline, capsys):
    cli.main(["calibrate", "--from-run", "phase2", "--variants", "hermes-subgoals"])
    assert "hermes-contract" not in capsys.readouterr().out


def ledger(tmp_path, total):
    path = tmp_path / "spend.md"
    path.write_text(f"| **Total** | **1** | **${total}** | **0** |\n", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "cap,spent,reason",
    [
        (None, "0", "explicit"),
        ("0.5", "0", "cap"),
        ("1", "19.01", "$20"),
        ("NaN", "0", "finite"),
        ("-1", "0", "nonnegative"),
    ],
)
def test_spend_guard_before_replay(offline, tmp_path, cap, spent, reason):
    with pytest.raises(ValueError, match=re.escape(reason)):
        calibrate.guard_spend(Decimal("1"), cap, ledger(tmp_path, spent))


def test_exact_stop_allowed_and_malformed_ledger_refused(tmp_path):
    calibrate.guard_spend(Decimal("1"), "1", ledger(tmp_path, "19"))
    path = ledger(tmp_path, "19")
    path.write_text("Billed total $19", encoding="utf-8")
    with pytest.raises(ValueError, match="Total"):
        calibrate.guard_spend(Decimal("1"), "1", path)


@pytest.mark.parametrize(
    "flags,reason",
    [
        ([], "confirm-spend"),
        (["--confirm-spend", "0.01"], "cap"),
        (["--confirm-spend", "3"], "per-task contract"),
    ],
)
def test_live_refusal_before_client_or_replay(offline, flags, reason):
    with pytest.raises(SystemExit, match=reason):
        cli.main(["calibrate", "--from-run", "phase2", "--live", *flags])


def test_cli_stop_guard_with_replay_mocked(offline, monkeypatch):
    monkeypatch.setattr(calibrate, "cumulative_spend", lambda path: Decimal("19"))
    with pytest.raises(SystemExit, match=r"\$20"):
        cli.main(["calibrate", "--from-run", "phase2", "--live", "--confirm-spend", "3"])


def test_templates_match_pinned_hermes():
    b = make_boundary()
    for name, template in calibrate.TEMPLATES.items():
        spec = dict(template=name)
        subgoals = {}
        common = dict(
            goal=b.goal,
            response=b.last_response,
            background_block="",
            current_time=judge.format_time(b.ts),
        )
        if "CONTRACT" in name:
            contract = dict(outcome="A", verification="B")
            spec.update(needs_per_task_contract=True, contracts={b.task_id: contract})
            common["contract_block"] = hg.GoalContract.from_dict(contract).render_block()
        else:
            subgoals = {b.task_id: ["A", "B"]}
            common["subgoals_block"] = "1. A\n2. B"
        result = calibrate.messages(
            b, prompt="new", view="head4k", specs={"new": spec}, subgoals=subgoals
        )
        assert result[1]["content"] == template.format(**common)
        assert result[0]["content"] == hg.JUDGE_SYSTEM_PROMPT
    assert calibrate.compute_metrics([], {}) is NotImplemented


def hash_entry(digest, date="2026-10-14"):
    return f"**{date}. Subgoals note.**\n\nconfigs/subgoals.toml sha256: {digest}\n"


@pytest.fixture
def subgoals_files(tmp_path, monkeypatch):
    subgoals = tmp_path / "subgoals.toml"
    subgoals.write_bytes(calibrate.SUBGOALS.read_bytes())
    prereg = tmp_path / "prereg.md"
    digest = hashlib.sha256(subgoals.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    prereg.write_text(hash_entry(digest), encoding="utf-8")
    monkeypatch.setattr(calibrate, "SUBGOALS", subgoals)
    monkeypatch.setattr(calibrate, "PREREG", prereg)
    return subgoals, prereg, digest


def subgoals_cli(*flags):
    return cli.main(
        [
            "calibrate",
            "--from-run",
            "phase2",
            "--variants",
            "hermes-subgoals",
            *flags,
        ]
    )


def test_matching_hash_still_refuses_empty_subgoals(offline, subgoals_files):
    with pytest.raises(SystemExit, match="needs per-task subgoals"):
        subgoals_cli("--live", "--confirm-spend", "3")


@pytest.mark.parametrize("missing", [False, True])
def test_hash_refusal_before_clients_and_replay(offline, subgoals_files, capsys, missing):
    subgoals, prereg, _ = subgoals_files
    if missing:
        prereg.write_text("**2026-10-14. No hash recorded.**\n", encoding="utf-8")
        reason, status = "no subgoals hash recorded", "NOT RECORDED"
    else:
        with subgoals.open("ab") as f:
            f.write(b"# Changed file\n")
        reason, status = "subgoals hash differs", "MISMATCH"
    with pytest.raises(SystemExit, match=reason):
        subgoals_cli("--live", "--confirm-spend", "3")
    assert subgoals_cli("--dry-run") == 0
    assert f"Subgoals prereg hash: {status}" in capsys.readouterr().out


@pytest.mark.parametrize("same_date", [False, True])
def test_latest_dated_hash_used(offline, subgoals_files, same_date):
    _, prereg, digest = subgoals_files
    old = "0" * 64
    text = hash_entry(old, "2026-10-14" if same_date else "2026-10-13")
    text += hash_entry(digest)
    if not same_date:
        text += hash_entry(old, "2026-10-12")
    text += "**2026-10-15. Unrelated note without a hash.**\n"
    prereg.write_text(text, encoding="utf-8")
    assert calibrate.latest_subgoals_hash(prereg) == digest
    with pytest.raises(SystemExit, match="needs per-task subgoals"):
        subgoals_cli("--live", "--confirm-spend", "3")


def test_committed_placeholder_matches_prereg():
    import tomllib

    raw = calibrate.SUBGOALS.read_bytes().replace(b"\r\n", b"\n")
    assert tomllib.loads(raw.decode("utf-8")) == {}
    assert hashlib.sha256(raw).hexdigest() == calibrate.latest_subgoals_hash(calibrate.PREREG)


def test_live_dispatch_is_only_mocked(offline, subgoals_files, tmp_path, monkeypatch):
    from hjr.config import load_judge_config

    b = make_boundary()
    cfg_path = tmp_path / "calibrate.toml"
    cfg_path.write_bytes(calibrate.CONFIG.read_bytes())
    subgoals, prereg, _ = subgoals_files
    subgoals.write_bytes(f'"{b.task_id}" = ["User criterion"]\r\n'.encode())
    digest = hashlib.sha256(subgoals.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    prereg.write_text(hash_entry(digest), encoding="utf-8")
    data_spec = dict(
        template="JUDGE_USER_PROMPT_WITH_SUBGOALS_TEMPLATE",
        model="flash",
        view="head4k",
        samples=3,
    )
    monkeypatch.setattr(calibrate, "CONFIG", cfg_path)
    monkeypatch.setattr(cli, "RUNS", tmp_path)
    monkeypatch.setattr(
        calibrate,
        "plans",
        lambda *a: [
            calibrate.Plan("source", "weak", "hermes-subgoals", data_spec, [b], Decimal("0.006"))
        ],
    )
    monkeypatch.setattr(calibrate, "cumulative_spend", lambda p: Decimal("7"))
    calls = []

    def fake_replay(boundaries, variants, **kwargs):
        calls.append(kwargs)
        assert boundaries == [b]
        assert kwargs["build_messages"](b, prompt=variants[0].prompt, view="head4k")
        return Counter(parsed=3)

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        complete = forbidden

    monkeypatch.setattr(calibrate, "replay", fake_replay)
    monkeypatch.setattr("hjr.client.JudgeClient", FakeClient)
    assert (
        cli.main(
            [
                "calibrate",
                "--from-run",
                "source",
                "--live",
                "--confirm-spend",
                "0.01",
                "--variants",
                "hermes-subgoals",
            ]
        )
        == 0
    )
    assert len(calls) == 1
    assert calls[0]["arms"] == load_judge_config(cfg_path).models
    record = json.loads(next(tmp_path.glob("calibrate-*/calibration.json")).read_text())
    assert record["agent_arm"] == "weak"
    assert record["subgoals_sha256"] == digest
    assert next(tmp_path.glob("calibrate-*/subgoals.toml")).read_bytes() == subgoals.read_bytes()
