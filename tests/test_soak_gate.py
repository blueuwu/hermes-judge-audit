from __future__ import annotations

import copy
import typing
from pathlib import Path

from hjr import soak

GATE = soak.load_gate()
TASKS = ["hjr/c1-01-csv-to-json", "hjr/c3-02-missing-sqlite"]


def _gate():
    g = copy.deepcopy(GATE)
    g["gate"]["tasks"] = TASKS
    return g


def _report(**changes):
    segments = {
        "early": soak.Segment(turns=[1, 2], tool_calls=20),
        "resumed": soak.Segment(
            turns=[5, 6],
            tool_calls=15,
            context_tokens=42_000,
            resumes_attempted=5,
            resumes_passed=5,
        ),
        "concurrent": soak.Segment(turns=[1, 2, 3], tool_calls=20, concurrency=8),
    }
    fields = {"arm_id": "abc", "tasks": TASKS, "segments": segments, "events": []}
    fields.update(changes)
    return soak.SoakReport(**fields)


def _event(type_, recovered):
    return soak.CorruptionEvent(
        type=type_, recovered=recovered, task_id=TASKS[0], trial="t1", turn=3
    )


def test_committed_gate_matches_preregistration():
    g = GATE["gate"]
    assert (g["min_tool_calls"], g["max_recovered_events"], g["max_unrecovered_events"]) == (
        50,
        1,
        0,
    )
    assert (g["resumes_required"], g["resumes_passed_required"]) == (5, 5)
    assert set(GATE["corruption_types"]) == set(typing.get_args(soak.CorruptionType))
    assert set(GATE["segments"]) == {"early", "resumed", "concurrent"}
    assert GATE["segments"]["resumed"]["min_context_tokens"] == 30_000
    assert GATE["segments"]["resumed"]["max_context_tokens"] == 60_000


def test_clean_soak_passes():
    result = soak.evaluate(_report(), _gate())
    assert result.passed, result.failures
    assert result.counts["tool_calls"] == 55


def test_committed_gate_names_the_two_m1_tasks():
    tasks_dir = Path(__file__).resolve().parents[1] / "tasks"
    assert GATE["gate"]["tasks"] == TASKS
    assert all((tasks_dir / t.removeprefix("hjr/") / "task.toml").is_file() for t in TASKS)


def test_gate_without_tasks_cannot_pass():
    empty = copy.deepcopy(GATE)
    empty["gate"]["tasks"] = []
    result = soak.evaluate(_report(), empty)
    assert not result.passed
    assert any("no tasks" in f for f in result.failures)


def test_one_recovered_event_allowed_two_not():
    one = soak.evaluate(_report(events=[_event("empty_completion", True)]), _gate())
    two = soak.evaluate(
        _report(events=[_event("empty_completion", True), _event("length_mid_call", True)]),
        _gate(),
    )
    assert one.passed and not two.passed


def test_any_unrecovered_event_fails():
    result = soak.evaluate(_report(events=[_event("resume_rejected", False)]), _gate())
    assert not result.passed
    assert result.counts["events.resume_rejected"] == 1


def test_coverage_rules():
    segs = dict(_report().segments)
    segs["resumed"] = segs["resumed"].model_copy(update={"context_tokens": 12_000})
    del segs["concurrent"]
    result = soak.evaluate(_report(segments=segs), _gate())
    assert any("context 12000" in f for f in result.failures)
    assert any("missing mandatory segment 'concurrent'" in f for f in result.failures)


def test_too_few_calls_or_failed_resume():
    segs = dict(_report().segments)
    segs["resumed"] = segs["resumed"].model_copy(update={"resumes_passed": 4, "tool_calls": 5})
    result = soak.evaluate(_report(segments=segs), _gate())
    assert any("tool calls" in f for f in result.failures)
    assert any("resumes passed" in f for f in result.failures)


def test_recovery_that_leaves_history_counts_as_unrecovered():
    event = _event("invalid_arguments", True).model_copy(update={"left_in_history": True})
    result = soak.evaluate(_report(events=[event]), _gate())
    assert not result.passed
    assert (result.counts["recovered_events"], result.counts["unrecovered_events"]) == (0, 1)


def test_rejected_resume_fails_even_when_recovered():
    result = soak.evaluate(_report(events=[_event("resume_rejected", True)]), _gate())
    assert not result.passed
    assert any("resumed histories rejected" in f for f in result.failures)


def test_concurrency_floor_is_six_peak_in_flight():
    assert GATE["segments"]["concurrent"]["min_concurrency"] == 6
    segs = dict(_report().segments)
    segs["concurrent"] = segs["concurrent"].model_copy(update={"concurrency": 5, "rate_limited": 3})
    result = soak.evaluate(_report(segments=segs), _gate())
    assert any("concurrency 5 < 6" in f for f in result.failures)
    assert result.counts["rate_limited"] == 3
