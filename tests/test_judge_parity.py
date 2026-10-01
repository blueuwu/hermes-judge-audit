"""The replayed prod-* prompts must match what Hermes ``judge_goal`` sends, byte for byte."""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from hermes_cli import goals as hg

from hjr import judge
from tests.factories import make_boundary

FROZEN = datetime(2026, 10, 5, 14, 2, 11, tzinfo=UTC)


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: ARG003 - mirrors datetime.now
        return cls.fromtimestamp(FROZEN.timestamp(), tz=FROZEN.tzinfo)

    def astimezone(self, tz=None):
        # Production converts to the host's local zone; pin it so the test is host-independent.
        return self if tz is None else super().astimezone(tz)


@pytest.fixture
def captured(monkeypatch):
    calls: list[dict] = []

    def fake_call_llm(**kwargs):
        calls.append(kwargs)
        content = '{"verdict": "continue", "reason": "stub"}'
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    module = types.ModuleType("agent.auxiliary_client")
    module.call_llm = fake_call_llm
    monkeypatch.setitem(sys.modules, "agent.auxiliary_client", module)
    monkeypatch.setattr(hg, "datetime", _FrozenDatetime)
    monkeypatch.setattr(hg, "_goal_judge_max_tokens", lambda: hg.DEFAULT_JUDGE_MAX_TOKENS)
    monkeypatch.setattr(hg, "_goal_judge_timeout", lambda: hg.DEFAULT_JUDGE_TIMEOUT)
    return calls


RESPONSES = {
    "short": "Created `report.csv` with 12 rows. All tests pass.",
    "exact_limit": "x" * judge.RESPONSE_CHARS,
    "over_limit": "Summary.\n" + "line of detail\n" * 400 + "Note: two tests still fail.",
    "unicode": "完成 ✅ — wrote `données.json` (3 KB)\n" * 150,
}
GOALS = {
    "plain": "Add a `--json` flag to cli.py that prints results as JSON.",
    "long": "Refactor the parser. " * 150,
}


@pytest.mark.parametrize("response_key", sorted(RESPONSES))
@pytest.mark.parametrize("goal_key", sorted(GOALS))
def test_prod_plain_matches_judge_goal(captured, goal_key, response_key):
    goal, response = GOALS[goal_key], RESPONSES[response_key]
    hg.judge_goal(goal, response)
    boundary = make_boundary(goal=goal, last_response=response, ts=FROZEN)
    sent = captured[0]["messages"]
    assert judge.build_messages(boundary, prompt="prod-plain", view="head4k") == sent


def test_prod_contract_matches_judge_goal(captured):
    contract = hg.GoalContract(
        verification="pytest -q passes",
        constraints="do not edit tests/",
        boundaries="src/ only",
    )
    goal, response = GOALS["plain"], RESPONSES["over_limit"]
    hg.judge_goal(goal, response, contract=contract)
    boundary = make_boundary(
        goal=goal, last_response=response, contract=contract.to_dict(), ts=FROZEN
    )
    sent = captured[0]["messages"]
    assert judge.build_messages(boundary, prompt="prod-contract", view="head4k") == sent


def test_sampling_parameters_match_production(captured):
    hg.judge_goal(GOALS["plain"], RESPONSES["short"])
    call = captured[0]
    assert call["task"] == "goal_judge"
    assert call["temperature"] == judge.TEMPERATURE
    assert call["max_tokens"] == judge.MAX_TOKENS


def test_non_utc_timestamp_renders_its_own_zone():
    ist = timezone(timedelta(hours=5, minutes=30))
    ts = FROZEN.astimezone(ist)
    boundary = make_boundary(ts=ts)
    user = judge.build_messages(boundary, prompt="prod-plain", view="head4k")[1]["content"]
    assert "Current time: 2026-10-05 19:32:11" in user


def test_naive_timestamp_rejected():
    with pytest.raises(ValueError):
        judge.format_time(datetime(2026, 10, 5))


BACKGROUND = [
    {
        "pid": 4242,
        "session_id": "proc_ci",
        "command": "gh run watch 123 --exit-status",
        "uptime_seconds": 95,
        "watch_patterns": ["completed"],
        "output_preview": "Run in progress\nbuild: queued",
        "status": "running",
    },
    {"pid": 77, "command": "npm run build", "notify_on_complete": True, "status": "running"},
    {"pid": 12, "command": "sleep 1", "status": "exited"},
]


@pytest.mark.parametrize(
    ("processes", "delegations"),
    [(BACKGROUND, 0), ([], 2), (BACKGROUND, 1)],
    ids=["processes", "delegations", "both"],
)
def test_background_block_matches_judge_goal(captured, processes, delegations):
    goal, response = GOALS["plain"], "Waiting on CI before calling this done."
    hg.judge_goal(goal, response, background_processes=processes, active_delegations=delegations)
    boundary = make_boundary(
        goal=goal,
        last_response=response,
        background_processes=processes,
        active_delegations=delegations,
        ts=FROZEN,
    )
    sent = captured[0]["messages"]
    assert judge.build_messages(boundary, prompt="prod-plain", view="head4k") == sent
    content = sent[1]["content"]
    assert ("pid 4242" in content) is bool(processes)
    assert "pid 12" not in content  # exited processes are dropped
    assert ("Active delegations" in content) is (delegations > 0)
