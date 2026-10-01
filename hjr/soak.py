"""Evaluate a soak report against the pre-registered compatibility gate.

Detection of the events themselves (from Hermes sessions and Harbor trial logs) lands with the
M1 harness; this module fixes what is counted and how the gate decides.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from hjr.config import CONFIGS

GATE_PATH = CONFIGS / "soak_gate.toml"

CorruptionType = Literal[
    "tool_call_as_text",
    "invalid_arguments",
    "length_mid_call",
    "empty_completion",
    "reasoning_leak",
    "resume_rejected",
]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CorruptionEvent(_M):
    type: CorruptionType
    recovered: bool
    task_id: str
    trial: str
    turn: int
    detail: str = ""


class Segment(_M):
    turns: list[int]
    tool_calls: int
    concurrency: int = 1
    context_tokens: int = 0  # peak prompt tokens observed in the segment
    resumes_attempted: int = 0
    resumes_passed: int = 0


class SoakReport(_M):
    arm_id: str
    tasks: list[str]
    segments: dict[str, Segment]
    events: list[CorruptionEvent] = Field(default_factory=list)


class GateResult(_M):
    passed: bool
    failures: list[str]
    counts: dict[str, int]


def load_gate(path: Path = GATE_PATH) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _segment_failures(name: str, seg: Segment | None, rule: dict) -> list[str]:
    if seg is None:
        return [f"missing mandatory segment {name!r}"]
    out = []
    if "max_turn" in rule and max(seg.turns, default=0) > rule["max_turn"]:
        out.append(f"{name}: turns {seg.turns} exceed {rule['max_turn']}")
    if "turns" in rule and not set(seg.turns) & set(rule["turns"]):
        out.append(f"{name}: none of turns {rule['turns']} covered")
    lo, hi = rule.get("min_context_tokens"), rule.get("max_context_tokens")
    if lo is not None and not lo <= seg.context_tokens <= hi:
        out.append(f"{name}: context {seg.context_tokens} outside [{lo}, {hi}]")
    if "min_concurrency" in rule and seg.concurrency < rule["min_concurrency"]:
        out.append(f"{name}: concurrency {seg.concurrency} < {rule['min_concurrency']}")
    return out


def evaluate(report: SoakReport, gate: dict | None = None) -> GateResult:
    gate = gate or load_gate()
    g = gate["gate"]
    failures: list[str] = []

    if not g["tasks"]:
        failures.append("gate has no tasks: fill in the two M1 task ids before soaking")
    elif sorted(report.tasks) != sorted(g["tasks"]):
        failures.append(f"soak tasks {sorted(report.tasks)} != gate tasks {sorted(g['tasks'])}")

    unknown = {e.type for e in report.events} - set(gate["corruption_types"])
    if unknown:
        failures.append(f"event types not in the gate taxonomy: {sorted(unknown)}")

    segments = report.segments.values()
    tool_calls = sum(s.tool_calls for s in segments)
    recovered = sum(e.recovered for e in report.events)
    unrecovered = len(report.events) - recovered
    resumes = sum(s.resumes_attempted for s in segments)
    resumes_ok = sum(s.resumes_passed for s in segments)

    checks = [
        (tool_calls < g["min_tool_calls"], f"{tool_calls} tool calls < {g['min_tool_calls']}"),
        (
            recovered > g["max_recovered_events"],
            f"{recovered} recovered events > {g['max_recovered_events']}",
        ),
        (
            unrecovered > g["max_unrecovered_events"],
            f"{unrecovered} unrecovered events > {g['max_unrecovered_events']}",
        ),
        (resumes < g["resumes_required"], f"{resumes} resumes attempted < {g['resumes_required']}"),
        (
            resumes_ok < g["resumes_passed_required"],
            f"{resumes_ok} resumes passed < {g['resumes_passed_required']}",
        ),
    ]
    failures += [msg for bad, msg in checks if bad]
    for name, rule in gate["segments"].items():
        failures += _segment_failures(name, report.segments.get(name), rule)

    counts = {
        "tool_calls": tool_calls,
        "recovered_events": recovered,
        "unrecovered_events": unrecovered,
        "resumes_attempted": resumes,
        "resumes_passed": resumes_ok,
        **{
            f"events.{t}": sum(e.type == t for e in report.events) for t in gate["corruption_types"]
        },
    }
    return GateResult(passed=not failures, failures=failures, counts=counts)
