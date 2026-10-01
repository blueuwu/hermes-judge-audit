"""Fixtures for the production parser shapes the replay must handle."""

from __future__ import annotations

import pytest

from hjr.judge import parse_verdict

CASES = [
    # (raw reply, verdict, decision, parse_failed)
    ('{"verdict": "done", "reason": "file exists"}', "done", "done", False),
    ('{"verdict": "BLOCKED", "reason": "needs API key"}', "blocked", "blocked", False),
    ('{"verdict": "continue", "reason": "tests fail"}', "continue", "continue", False),
    ('```json\n{"verdict": "done", "reason": "ok"}\n```', "done", "done", False),
    ('Sure. {"verdict": "done", "reason": "ok"} Hope that helps.', "done", "done", False),
    ('{"done": true, "reason": "legacy"}', "done", "done", False),
    ('{"done": "false", "reason": "legacy string"}', "continue", "continue", False),
    ('{"verdict": "wait", "wait_for_seconds": 60, "reason": "ci"}', "wait", "continue", False),
    ('{"verdict": "wait", "reason": "no target"}', "continue", "continue", False),
    ('{"verdict": "finished", "reason": "odd label"}', "continue", "continue", False),
    ("The goal is done.", "continue", "continue", True),
    ("", "continue", "continue", True),
]


@pytest.mark.parametrize(("raw", "verdict", "decision", "parse_failed"), CASES)
def test_parse_verdict(raw, verdict, decision, parse_failed):
    parsed = parse_verdict(raw)
    assert parsed.verdict == verdict
    assert parsed.decision == decision
    assert parsed.parse_failed is parse_failed
