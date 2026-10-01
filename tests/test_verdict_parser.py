"""Offline fixtures for Hermes's judge-reply parser. Zero API calls.

Every case runs through ``hermes_cli.goals._parse_judge_response`` via ``hjr.judge.parse_verdict``.
Expectations record what production does, including the cases marked QUIRK, where production
behaviour is arguably wrong; those are findings to report, not behaviour to fix here.
"""

from __future__ import annotations

import json

import pytest
from hermes_cli import goals as hg

from hjr.judge import MISSING_VERDICT, UNKNOWN_LABEL, WAIT_WITHOUT_TARGET, parse_verdict

LONG_REASON = "The response lists every file and quotes the test output. " * 350

# (id, raw reply, verdict, parse_failed, format_violation)
CASES = [
    # Current schema, all four verdicts
    ("done", '{"verdict": "done", "reason": "file exists"}', "done", False, None),
    ("continue", '{"verdict": "continue", "reason": "tests fail"}', "continue", False, None),
    ("blocked", '{"verdict": "blocked", "reason": "needs a key"}', "blocked", False, None),
    ("label-case-space", '{"verdict": "  DONE ", "reason": "x"}', "done", False, None),
    ("no-reason", '{"verdict": "done"}', "done", False, None),
    # WAIT: each target and alias, in Hermes's priority order
    (
        "wait-session",
        '{"verdict": "wait", "wait_on_session": "s1", "reason": "ci"}',
        "wait",
        False,
        None,
    ),
    (
        "wait-session-alias",
        '{"verdict": "wait", "session_id": "s1", "reason": "ci"}',
        "wait",
        False,
        None,
    ),
    (
        "wait-pid",
        '{"verdict": "wait", "wait_on_pid": 4242, "reason": "build"}',
        "wait",
        False,
        None,
    ),
    (
        "wait-pid-string",
        '{"verdict": "wait", "pid": "4242", "reason": "build"}',
        "wait",
        False,
        None,
    ),
    (
        "wait-seconds",
        '{"verdict": "wait", "wait_for_seconds": 900, "reason": "rate limit"}',
        "wait",
        False,
        None,
    ),
    (
        "wait-no-target",
        '{"verdict": "wait", "reason": "waiting"}',
        "continue",
        False,
        WAIT_WITHOUT_TARGET,
    ),
    (
        "wait-zero-pid",
        '{"verdict": "wait", "wait_on_pid": 0, "reason": "x"}',
        "continue",
        False,
        WAIT_WITHOUT_TARGET,
    ),
    (
        "wait-bad-seconds",
        '{"verdict": "wait", "wait_for_seconds": "soon", "reason": "x"}',
        "continue",
        False,
        WAIT_WITHOUT_TARGET,
    ),
    # Legacy {"done": ...}
    ("legacy-true", '{"done": true, "reason": "legacy"}', "done", False, None),
    ("legacy-false", '{"done": false, "reason": "legacy"}', "continue", False, None),
    ("legacy-string-yes", '{"done": "yes", "reason": "legacy"}', "done", False, None),
    ("legacy-string-false", '{"done": "false", "reason": "legacy"}', "continue", False, None),
    ("legacy-zero", '{"done": 0, "reason": "legacy"}', "continue", False, None),
    # Contract violations Hermes coerces to CONTINUE without flagging parse_failed
    ("unknown-label", '{"verdict": "finished", "reason": "odd"}', "continue", False, UNKNOWN_LABEL),
    ("null-verdict", '{"verdict": null, "reason": "x"}', "continue", False, MISSING_VERDICT),
    ("no-verdict-key", '{"reason": "looks complete"}', "continue", False, MISSING_VERDICT),
    # Wrappers
    ("fenced-json", '```json\n{"verdict": "done", "reason": "ok"}\n```', "done", False, None),
    ("fenced-bare", '```\n{"verdict": "done", "reason": "ok"}\n```', "done", False, None),
    ("fenced-inline", '```{"verdict": "done", "reason": "ok"}```', "done", False, None),
    (
        "prose-wrapped",
        'Here is my verdict: {"verdict": "done", "reason": "ok"} Thanks.',
        "done",
        False,
        None,
    ),
    # Escaping and length
    (
        "escaped-quotes-newlines",
        json.dumps({"verdict": "continue", "reason": 'it printed "FAIL"\nthen exited 1'}),
        "continue",
        False,
        None,
    ),
    (
        "unicode-escapes",
        '{"verdict": "done", "reason": "\\u2705 all four files"}',
        "done",
        False,
        None,
    ),
    (
        "long-reason",
        json.dumps({"verdict": "continue", "reason": LONG_REASON}),
        "continue",
        False,
        None,
    ),
    # JSON-looking text inside the reason: fine when the whole reply is one JSON object
    (
        "json-in-reason",
        json.dumps({"verdict": "continue", "reason": 'file says {"verdict": "done"}'}),
        "continue",
        False,
        None,
    ),
    # QUIRK: prose-wrapped reply whose reason contains "}" -- the lazy regex stops at the first
    # brace, the fragment is invalid JSON, and the reply counts as unparseable.
    (
        "quirk-brace-in-wrapped-reason",
        'Verdict: {"verdict": "done", "reason": "returns {} when empty"}',
        "continue",
        True,
        None,
    ),
    # QUIRK: a decoy object before the real verdict wins, because the first match is taken.
    (
        "quirk-decoy-first",
        'Format: {"verdict": "done"}. My answer: {"verdict": "continue", "reason": "tests fail"}',
        "done",
        False,
        None,
    ),
    # Failures
    ("empty", "", "continue", True, None),
    ("whitespace", "   \n ", "continue", True, None),
    ("prose-only", "The goal is done.", "continue", True, None),
    ("json-array", '[{"verdict": "done", "reason": "ok"}]', "continue", True, None),
    ("truncated-json", '{"verdict": "done", "reason": "the file', "continue", True, None),
]


@pytest.mark.parametrize(
    ("raw", "verdict", "parse_failed", "violation"),
    [c[1:] for c in CASES],
    ids=[c[0] for c in CASES],
)
def test_parse_verdict(raw, verdict, parse_failed, violation):
    parsed = parse_verdict(raw)
    assert parsed.verdict == verdict
    assert parsed.parse_failed is parse_failed
    assert parsed.format_violation == violation


@pytest.mark.parametrize("raw", [c[1] for c in CASES], ids=[c[0] for c in CASES])
def test_wrapper_never_changes_hermes_result(raw):
    verdict, reason, parse_failed, _ = hg._parse_judge_response(raw)
    parsed = parse_verdict(raw)
    assert (parsed.verdict, parsed.reason, parsed.parse_failed) == (verdict, reason, parse_failed)


def test_outcome_and_decision():
    assert parse_verdict("").outcome == "parse_failed"
    assert parse_verdict('{"verdict": "finished"}').outcome == "format_violation"
    ok = parse_verdict('{"verdict": "wait", "wait_for_seconds": 60, "reason": "ci"}')
    assert ok.outcome == "parsed" and ok.decision == "continue"


def test_long_reason_kept_whole():
    assert parse_verdict(json.dumps({"verdict": "done", "reason": LONG_REASON})).reason == (
        LONG_REASON.strip()
    )
