from __future__ import annotations

import json

import pytest
from hermes_cli import goals as hg

from hjr import goalloop


def _assistant(content="", calls=()):
    msg = {"role": "assistant", "content": content}
    if calls:
        msg["tool_calls"] = [
            {"id": cid, "type": "function", "function": {"name": name, "arguments": args}}
            for cid, name, args in calls
        ]
    return msg


def _tool(cid, content):
    return {"role": "tool", "tool_call_id": cid, "content": content}


def test_turn_prompts_match_hermes():
    assert goalloop.turn_prompt("Do X.", 1) == "Do X."
    assert goalloop.turn_prompt("Do X.", 2) == hg.CONTINUATION_PROMPT_TEMPLATE.format(goal="Do X.")


def test_last_assistant_text_mirrors_the_cli():
    messages = [
        {"role": "user", "content": "go"},
        _assistant("", [("c1", "terminal", '{"command": "ls"}')]),
        _tool("c1", "a b"),
        _assistant([{"type": "text", "text": "Done."}, {"type": "image_url"}]),
    ]
    assert goalloop.last_assistant_text(messages) == "Done."
    # the newest assistant message wins even when it is only a tool call
    assert goalloop.last_assistant_text(messages[:3]) == ""
    assert goalloop.last_assistant_text([]) == ""


def test_failed_turn_notice_is_judged_but_marked():
    notice = "Your request was not processed. Send it again if you still want me to carry it out."
    messages = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": notice, "display_kind": "failed_turn"},
    ]
    assert goalloop.last_assistant_text(messages) == notice
    assert goalloop.last_assistant_kind(messages) == "failed_turn"
    assert goalloop.last_assistant_kind(messages[:1]) == ""


def test_tool_events_pair_calls_with_results():
    messages = [
        _assistant("", [("c1", "terminal", '{"command": "bin/migrate.sh m.sql"}')]),
        _tool("c1", json.dumps({"output": "sqlite3: not found", "exit_code": 127})),
        _assistant("", [("c2", "write_file", '{"path": "x.py", "content": "print(1)"}')]),
        _tool("c2", "ok"),
        _assistant("", [("c3", "terminal", "{not json")]),
    ]
    events = goalloop.tool_events(messages)
    assert [(e.tool, e.exit) for e in events] == [
        ("terminal", 127),
        ("write_file", None),
        ("terminal", None),
    ]
    assert events[0].cmd == "bin/migrate.sh m.sql"
    assert "sqlite3: not found" in events[0].out_tail
    assert json.loads(events[1].cmd)["path"] == "x.py"
    assert events[2].cmd == json.dumps({"raw": "{not json"})
    assert goalloop.count_tool_calls(messages) == 3


def test_session_export_must_hold_one_session():
    line = json.dumps({"id": "s1", "messages": [{"role": "user", "content": "hi"}]})
    assert goalloop.parse_session_export(line + "\n") == ("s1", [{"role": "user", "content": "hi"}])
    assert goalloop.parse_session_export("") == (None, [])
    with pytest.raises(ValueError, match="one session"):
        goalloop.parse_session_export(line + "\n" + line)


def test_done_and_blocked_stop_the_loop():
    assert goalloop.LoopState(6).after_turn("ok", verdict="done") == "done"
    assert goalloop.LoopState(6).after_turn("ok", verdict="blocked") == "blocked"
    assert goalloop.LoopState(6).after_turn("ok", verdict="wait") == "continue"


def test_empty_response_stops_without_using_a_turn():
    state = goalloop.LoopState(6)
    assert state.after_turn("  \n", verdict=None) == "empty_response"
    assert state.turns_used == 0


def test_budget_pauses_on_the_last_turn():
    state = goalloop.LoopState(2)
    assert state.after_turn("x", verdict="continue") == "continue"
    assert state.after_turn("x", verdict="continue") == "budget"


def test_auto_pause_thresholds_match_hermes():
    parse = goalloop.LoopState(20)
    actions = [parse.after_turn("x", verdict="continue", parse_failed=True) for _ in range(3)]
    assert actions == ["continue", "continue", "pause_parse"]
    assert goalloop.MAX_PARSE_FAILURES == 3

    transport = goalloop.LoopState(20)
    actions = [transport.after_turn("x", verdict=None, transport_failed=True) for _ in range(5)]
    assert actions[-1] == "pause_transport" and set(actions[:-1]) == {"continue"}
    assert goalloop.MAX_TRANSPORT_FAILURES == 5


def test_a_usable_reply_resets_the_failure_streaks():
    state = goalloop.LoopState(20)
    state.after_turn("x", verdict="continue", parse_failed=True)
    state.after_turn("x", verdict="continue", parse_failed=True)
    state.after_turn("x", verdict="continue")
    assert state.parse_failures == 0
    assert state.after_turn("x", verdict="continue", parse_failed=True) == "continue"
