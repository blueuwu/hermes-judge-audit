from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from hjr.schemas import ToolEvent, TurnRecord
from hjr.soakreport import build_report, detect_events, peak_overlap, read_trial

TS = datetime(2026, 10, 1, tzinfo=UTC)
KW = {"task_id": "hjr/c1-01-csv-to-json", "trial": "t", "turn": 3}


def _call(args: str, name: str = "terminal") -> dict:
    return {"id": "c", "type": "function", "function": {"name": name, "arguments": args}}


def _types(messages) -> list[str]:
    return [e.type for e in detect_events(messages, **KW)]


def test_clean_messages_have_no_events():
    messages = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "", "tool_calls": [_call('{"command": "ls"}')]},
        {"role": "tool", "tool_call_id": "c", "content": "a"},
        {"role": "assistant", "content": "Done.", "finish_reason": "stop"},
    ]
    assert _types(messages) == []


def test_each_protocol_event_is_detected_and_unrecovered():
    messages = [
        {"role": "assistant", "content": '<tool_call>{"name": "terminal"}</tool_call>'},
        {"role": "assistant", "content": "", "tool_calls": [_call('{"command": "ls')]},
        {
            "role": "assistant",
            "content": "",
            "finish_reason": "length",
            "tool_calls": [_call("{}")],
        },
        {"role": "assistant", "content": "   "},
        {"role": "assistant", "content": "<think>plan</think> Done."},
    ]
    events = detect_events(messages, **KW)
    assert [e.type for e in events] == [
        "tool_call_as_text",
        "invalid_arguments",
        "length_mid_call",
        "empty_completion",
        "reasoning_leak",
    ]
    assert all(not e.recovered and e.left_in_history and not e.clean_recovery for e in events)


def test_failed_turn_notice_is_not_an_empty_completion():
    notice = {"role": "assistant", "content": "", "display_kind": "failed_turn"}
    assert _types([notice]) == []


def test_a_reply_that_mentions_json_is_not_a_tool_call():
    assert _types([{"role": "assistant", "content": 'Wrote {"orders": 32} to totals.json.'}]) == []


def test_peak_overlap_counts_simultaneous_requests():
    assert peak_overlap([]) == 0
    assert peak_overlap([(0, 2), (1, 3), (2.5, 4), (5, 6)]) == 2
    assert peak_overlap([(0, 10)] * 6) == 6
    assert peak_overlap([(0, 1), (1, 2)]) == 1  # back to back is not concurrent


def _session(messages: list[dict]) -> str:
    return json.dumps({"id": "s1", "system_prompt": "sys", "messages": messages}) + "\n"


def _turn(n: int, kind: str = "", code: int = 0, tools: int = 0, ctx: int = 0) -> TurnRecord:
    return TurnRecord(
        boundary_id=f"job/t/b{n:02d}",
        run_id="job",
        trial="c1-01-csv-to-json__x",
        task_id="hjr/c1-01-csv-to-json",
        agent_arm="strong",
        agent_model="deepseek/deepseek-v4.1-flash",
        turn=n,
        prompt="p",
        goal="g",
        last_response="r",
        last_response_kind=kind,
        response_chars=1,
        context_tokens_est=ctx,
        session_id="s1",
        recent_tool_events=[ToolEvent(tool="terminal", cmd="ls")] * tools,
        snapshot=f"b{n:02d}.tgz",
        action="continue",
        agent_exit_code=code,
        past_stop=n > 1,
        ts=TS,
    )


def _write_trial(job: Path) -> Path:
    agent = job / "c1-01-csv-to-json__x" / "agent"
    agent.mkdir(parents=True)
    history = []
    turns = []
    for n in range(1, 7):
        rejected = n == 6
        history += [{"role": "user", "content": f"turn {n}", "timestamp": 10 * n}]
        if rejected:
            history.append(
                {
                    "role": "assistant",
                    "content": "Your request was not processed.",
                    "display_kind": "failed_turn",
                    "timestamp": 10 * n + 1,
                }
            )
            output = "Provider said: HTTP 400: reasoning_content must be passed back\n"
        else:
            history += [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [_call('{"command": "ls"}')],
                    "timestamp": 10 * n + 2,
                },
                {"role": "tool", "tool_call_id": "c", "content": "a", "timestamp": 10 * n + 3},
                {"role": "assistant", "content": "Done.", "timestamp": 10 * n + 5},
            ]
            output = "Done.\n"
        (agent / f"session_{n:02d}.jsonl").write_text(_session(history))
        (agent / f"turn_{n:02d}.txt").write_text(output)
        turns.append(
            _turn(
                n,
                "failed_turn" if rejected else "",
                1 if rejected else 0,
                0 if rejected else 1,
                ctx=20_000 + 3_000 * n,
            )
        )
    (agent / "turns.jsonl").write_text("".join(t.model_dump_json() + "\n" for t in turns))
    return job


def test_rejected_resume_and_coverage_from_a_trial(tmp_path):
    job = _write_trial(tmp_path / "job")
    trial = read_trial(job / "c1-01-csv-to-json__x")
    assert [(e.type, e.turn) for e in trial.events] == [("resume_rejected", 6)]
    assert "HTTP 400" in trial.events[0].detail
    assert trial.failed_turns == []
    assert len(trial.requests) == 10  # two requests per clean turn, none for the failed one

    built = build_report([job])
    segs = built.report.segments
    assert segs["resumed"].turns == [5, 6]
    assert segs["resumed"].context_tokens == 38_000
    assert (segs["resumed"].resumes_attempted, segs["resumed"].resumes_passed) == (2, 1)
    assert segs["early"].tool_calls == 2 and segs["early"].resumes_attempted == 1
    assert segs["concurrent"].concurrency == 1
    assert built.report.arm_id == "strong:deepseek/deepseek-v4.1-flash"


def test_rate_limit_pattern_ignores_log_timestamps():
    from hjr.soakreport import RATE_LIMITED

    assert not RATE_LIMITED.search("2026-10-01 16:25:48,429 INFO tools.registry: ok")
    assert RATE_LIMITED.search("Provider said: HTTP 429: too many requests")
