"""Build a SoakReport for one agent arm from Harbor soak jobs.

Everything is read back from what the harness saved per trial: ``turns.jsonl``, the session
export after every turn (``session_NN.jsonl``) and Hermes's own output (``turn_NN.txt``).

- Protocol events are detected in the exported history. Anything found there survived into the
  trajectory, so it counts as unrecovered (``left_in_history``) under the gate's rules.
- A failed turn (Hermes's ``failed_turn`` notice) on a resumed turn whose output shows an HTTP
  400 is a rejected resume. Other failed turns are infrastructure failures: listed, not events.
- Context is ``TurnRecord.context_tokens_est``: Hermes's own estimate, taken in the sandbox, of
  the system prompt and history the turn's last request carried. Tool schemas are not in the
  export, so it is a lower bound on the real request.
- Concurrency is the peak number of overlapping agent requests across all trials of a job, with
  each request spanning from the message before an assistant message to that message.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hjr.goalloop import parse_session_export
from hjr.schemas import TurnRecord, read_jsonl
from hjr.soak import CorruptionEvent, Segment, SoakReport

FAILED_TURN = "failed_turn"
TOOL_CALL_TEXT = re.compile(
    r"<tool_call>|</tool_call>|<function=|<\|tool_call|\"(name|function)\"\s*:\s*\""
    r"(terminal|execute_code|write_file|read_file|search_files|patch|process)\""
)
REASONING_TEXT = re.compile(r"</?think>|</?reasoning>")
RATE_LIMITED = re.compile(r"\b429\b")
HTTP_400 = re.compile(r"HTTP 400\b")
SEGMENTS = {"early": (1, 2), "middle": (3, 4), "resumed": (5, 6)}


@dataclass
class TrialSoak:
    trial: str
    task_id: str
    arm: str
    turns: list[TurnRecord]
    events: list[CorruptionEvent] = field(default_factory=list)
    failed_turns: list[dict[str, Any]] = field(default_factory=list)
    context_by_turn: dict[int, int] = field(default_factory=dict)
    requests: list[tuple[float, float]] = field(default_factory=list)
    rate_limited: int = 0


def _invalid_arguments(call: dict[str, Any]) -> bool:
    raw = (call.get("function") or {}).get("arguments", "")
    if isinstance(raw, dict):
        return False
    try:
        return not isinstance(json.loads(raw or "{}"), dict)
    except json.JSONDecodeError:
        return True


def detect_events(
    messages: list[dict[str, Any]], *, task_id: str, trial: str, turn: int
) -> list[CorruptionEvent]:
    """Protocol events in one turn's new messages. All of them are in the history."""
    events = []

    def add(kind: str, detail: str) -> None:
        events.append(
            CorruptionEvent(
                type=kind,
                recovered=False,
                left_in_history=True,
                task_id=task_id,
                trial=trial,
                turn=turn,
                detail=detail[:300],
            )
        )

    for msg in messages:
        if msg.get("role") != "assistant" or msg.get("display_kind") == FAILED_TURN:
            continue
        content = msg.get("content") or ""
        content = content if isinstance(content, str) else json.dumps(content)
        calls = msg.get("tool_calls") or []
        if msg.get("finish_reason") == "length":
            add("length_mid_call", f"finish_reason=length with {len(calls)} tool calls")
        for call in calls:
            if _invalid_arguments(call):
                name = (call.get("function") or {}).get("name", "?")
                add("invalid_arguments", f"{name}: {(call.get('function') or {}).get('arguments')}")
        if not calls and TOOL_CALL_TEXT.search(content):
            add("tool_call_as_text", content)
        if not calls and not content.strip():
            add("empty_completion", "assistant message with no content and no tool calls")
        if REASONING_TEXT.search(content):
            add("reasoning_leak", content)
    return events


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def _provider_said(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("Provider said:"):
            return line.removeprefix("Provider said:").strip()
    return output.strip().splitlines()[0] if output.strip() else ""


def read_trial(trial_dir: Path) -> TrialSoak | None:
    agent = trial_dir / "agent"
    turns_path = agent / "turns.jsonl"
    if not turns_path.is_file():
        return None
    turns = list(read_jsonl(turns_path, TurnRecord))
    if not turns:
        return None
    out = TrialSoak(trial_dir.name, turns[0].task_id, turns[0].agent_arm, turns)
    seen = 0
    for turn in turns:
        n = turn.turn
        out.context_by_turn[n] = turn.context_tokens_est
        export = _text(agent / f"session_{n:02d}.jsonl")
        output = _text(agent / f"turn_{n:02d}.txt")
        out.rate_limited += len(RATE_LIMITED.findall(output))
        if not export.strip():
            continue
        _, messages = parse_session_export(export)
        new = messages[seen:]
        seen = len(messages)
        out.events += detect_events(new, task_id=out.task_id, trial=out.trial, turn=n)
        prev = messages[len(messages) - len(new) - 1] if len(messages) > len(new) else None
        for msg in new:
            if msg.get("role") == "assistant" and msg.get("display_kind") != FAILED_TURN and prev:
                out.requests.append((float(prev["timestamp"]), float(msg["timestamp"])))
            prev = msg
        if turn.last_response_kind == FAILED_TURN:
            rejected = n >= 2 and bool(HTTP_400.search(output))
            if rejected:
                out.events.append(
                    CorruptionEvent(
                        type="resume_rejected",
                        recovered=False,
                        left_in_history=True,
                        task_id=out.task_id,
                        trial=out.trial,
                        turn=n,
                        detail=_provider_said(output)[:300],
                    )
                )
            else:
                out.failed_turns.append(
                    {"trial": out.trial, "turn": n, "reason": _provider_said(output)[:300]}
                )
    for log in sorted((agent / "hermes-logs").glob("*.log")):
        out.rate_limited += len(RATE_LIMITED.findall(_text(log)))
    return out


def peak_overlap(intervals: list[tuple[float, float]]) -> int:
    edges = sorted([(s, 1) for s, _ in intervals] + [(e, -1) for _, e in intervals])
    peak = live = 0
    for _, step in edges:  # ends sort before starts at the same instant
        live += step
        peak = max(peak, live)
    return peak


def _resumed(turn: TurnRecord) -> tuple[int, int]:
    if turn.turn < 2:
        return 0, 0
    ok = turn.agent_exit_code == 0 and turn.last_response_kind != FAILED_TURN
    return 1, int(ok)


@dataclass
class SoakBuild:
    report: SoakReport
    failed_turns: list[dict[str, Any]]
    trials: int
    context_by_trial: dict[str, dict[int, int]]


def build_report(job_dirs: list[Path]) -> SoakBuild:
    trials: list[TrialSoak] = []
    peak = 0
    for job in job_dirs:
        job_trials = [t for d in sorted(job.iterdir()) if d.is_dir() and (t := read_trial(d))]
        peak = max(peak, peak_overlap([r for t in job_trials for r in t.requests]))
        trials += job_trials
    if not trials:
        raise ValueError(f"no soak trials found in {[str(j) for j in job_dirs]}")
    arms = Counter((t.arm, t.turns[0].agent_model) for t in trials)
    if len(arms) > 1:
        raise ValueError(f"a soak covers one agent arm, found {dict(arms)}")
    (arm, model), _ = arms.most_common(1)[0]

    segments = {}
    for name, (lo, hi) in SEGMENTS.items():
        turns = [t for trial in trials for t in trial.turns if lo <= t.turn <= hi]
        resumes = [_resumed(t) for t in turns]
        segments[name] = Segment(
            turns=sorted({t.turn for t in turns}),
            tool_calls=sum(len(t.recent_tool_events) for t in turns),
            context_tokens=max(
                (trial.context_by_turn.get(n, 0) for trial in trials for n in range(lo, hi + 1)),
                default=0,
            ),
            resumes_attempted=sum(a for a, _ in resumes),
            resumes_passed=sum(p for _, p in resumes),
        )
    segments["concurrent"] = Segment(
        turns=sorted({t.turn for trial in trials for t in trial.turns}),
        tool_calls=0,  # already counted in the turn segments
        concurrency=peak,
        rate_limited=sum(t.rate_limited for t in trials),
    )
    report = SoakReport(
        arm_id=f"{arm}:{model}",
        tasks=sorted({t.task_id for t in trials}),
        segments=segments,
        events=[e for t in trials for e in t.events],
    )
    return SoakBuild(
        report=report,
        failed_turns=[f for t in trials for f in t.failed_turns],
        trials=len(trials),
        context_by_trial={t.trial: t.context_by_turn for t in trials},
    )
