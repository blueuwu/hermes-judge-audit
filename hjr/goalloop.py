"""The /goal loop as the harness drives it, mirrored from Hermes at the audited commit.

Hermes runs the loop inside its interactive CLI (``cli_loops_mixin._maybe_continue_goal_after_turn``
and ``GoalManager.evaluate_after_turn``). The harness drives the same loop from outside, one
``hermes chat --resume`` per turn, and reproduces its decisions here:

- turn 1 sends the goal text (``goal_kick_prompt`` in a fresh session), later turns send
  ``CONTINUATION_PROMPT_TEMPLATE``;
- an empty final response is not judged and nothing is queued, so the loop stops;
- DONE ends the goal and BLOCKED pauses it; anything else continues until the auto-pause
  thresholds (3 parse failures or 5 transport failures in a row) or the turn budget.

Nothing here talks to a model or a container; ``hjr.harness.agent`` does the I/O.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from hermes_cli import goals as hg

from hjr.schemas import ToolEvent

MAX_PARSE_FAILURES = hg.DEFAULT_MAX_CONSECUTIVE_PARSE_FAILURES
MAX_TRANSPORT_FAILURES = hg.DEFAULT_MAX_CONSECUTIVE_TRANSPORT_FAILURES
TOOL_OUTPUT_TAIL = 500

Action = Literal[
    "done", "blocked", "continue", "pause_parse", "pause_transport", "budget", "empty_response"
]


def turn_prompt(goal: str, turn: int) -> str:
    return goal if turn == 1 else hg.CONTINUATION_PROMPT_TEMPLATE.format(goal=goal)


# ── Session exports ───────────────────────────────────────────────────


def parse_session_export(text: str) -> tuple[str | None, list[dict[str, Any]]]:
    """Session id and messages from ``hermes sessions export`` JSONL (one session per line)."""
    sessions = [json.loads(line) for line in text.splitlines() if line.strip()]
    if not sessions:
        return None, []
    if len(sessions) > 1:
        ids = [s.get("id") for s in sessions]
        raise ValueError(f"expected one session in the export, got {len(sessions)}: {ids}")
    session = sessions[0]
    return session.get("id"), list(session.get("messages") or [])


def _text(content: Any) -> str:
    if isinstance(content, list):
        parts = [
            p.get("text", "")
            for p in content
            if isinstance(p, dict) and p.get("type") in {"text", "output_text"}
        ]
        return "\n".join(t for t in parts if t)
    return str(content or "")


def last_assistant_text(messages: Sequence[dict[str, Any]]) -> str:
    """What Hermes hands the judge: the newest assistant message's text, "" when none
    (``cli_loops_mixin._last_assistant_response_text``)."""
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            return _text(msg.get("content", ""))
    return ""


def last_assistant_kind(messages: Sequence[dict[str, Any]]) -> str:
    """``display_kind`` of that message. ``failed_turn`` marks the notice Hermes writes when a
    turn fails; the CLI still hands it to the judge, so it is recorded, not filtered."""
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            return str(msg.get("display_kind") or "")
    return ""


def _arguments(call: dict[str, Any]) -> dict[str, Any]:
    raw = (call.get("function") or {}).get("arguments", "")
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"raw": raw}
    return parsed if isinstance(parsed, dict) else {"raw": raw}


def _exit_code(output: str) -> int | None:
    try:
        parsed = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(parsed, dict):
        for key in ("exit_code", "returncode", "exit"):
            if isinstance(parsed.get(key), int):
                return parsed[key]
    return None


def tool_events(messages: Sequence[dict[str, Any]]) -> list[ToolEvent]:
    """Every tool call in order, paired with its result's exit code and output tail."""
    results = {
        m.get("tool_call_id"): _text(m.get("content", ""))
        for m in messages
        if m.get("role") == "tool"
    }
    events = []
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for call in msg.get("tool_calls") or []:
            args = _arguments(call)
            output = results.get(call.get("id"), "")
            cmd = args.get("command") or args.get("cmd") or json.dumps(args, sort_keys=True)
            events.append(
                ToolEvent(
                    tool=(call.get("function") or {}).get("name", "unknown"),
                    cmd=str(cmd),
                    exit=_exit_code(output),
                    out_tail=output[-TOOL_OUTPUT_TAIL:],
                )
            )
    return events


def count_tool_calls(messages: Iterable[dict[str, Any]]) -> int:
    return sum(len(m.get("tool_calls") or []) for m in messages if m.get("role") == "assistant")


# ── Decisions ─────────────────────────────────────────────────────────


@dataclass
class LoopState:
    """Counters ``GoalManager`` keeps across turns of one goal."""

    max_turns: int
    turns_used: int = 0
    parse_failures: int = 0
    transport_failures: int = 0
    history: list[Action] = field(default_factory=list)

    def after_turn(
        self,
        last_response: str,
        *,
        verdict: str | None,
        parse_failed: bool = False,
        transport_failed: bool = False,
    ) -> Action:
        """The action Hermes takes after a turn. ``verdict`` is None when no judge call was made."""
        if not last_response.strip():
            # The CLI returns before evaluate_after_turn: no turn counted, nothing queued.
            return self._record("empty_response")
        self.turns_used += 1
        self.parse_failures = self.parse_failures + 1 if parse_failed else 0
        self.transport_failures = self.transport_failures + 1 if transport_failed else 0
        if verdict == "blocked":
            return self._record("blocked")
        if verdict == "done":
            return self._record("done")
        if self.transport_failures >= MAX_TRANSPORT_FAILURES:
            return self._record("pause_transport")
        if self.parse_failures >= MAX_PARSE_FAILURES:
            return self._record("pause_parse")
        if self.turns_used >= self.max_turns:
            return self._record("budget")
        return self._record("continue")

    def _record(self, action: Action) -> Action:
        self.history.append(action)
        return action
