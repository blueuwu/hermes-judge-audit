"""Offline replay of the Hermes ``/goal`` completion judge.

Prompt text, truncation and verdict parsing are imported from the pinned Hermes checkout
(``third_party/hermes-agent``), so a ``prod-*`` variant sends exactly what
``hermes_cli.goals.judge_goal`` sends. ``tests/test_judge_parity.py`` enforces this byte for byte.

A judge variant is ``<prompt>:<model>:<view>``:

* prompt: ``prod-plain`` | ``prod-contract``
* model: a key from ``configs/judge_variants.toml``
* view: how the agent's final response is cut down before it reaches the judge
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from hermes_cli import goals as hg
from hermes_time import safe_strftime

from hjr.schemas import BoundaryRecord, ToolEvent

RESPONSE_CHARS = hg._JUDGE_RESPONSE_SNIPPET_CHARS
GOAL_CHARS = 2000
CONTRACT_CHARS = 2500
TIME_FORMAT = "%Y-%m-%d %H:%M:%S %Z"

# Production sampling parameters (``_call_goal_judge_llm``); max_tokens is the config default.
TEMPERATURE = 0.0
MAX_TOKENS = hg.DEFAULT_JUDGE_MAX_TOKENS

PROMPTS = ("prod-plain", "prod-contract")
VIEWS = ("head4k", "headtail4k", "evidence")

HEADTAIL_MARKER = "\n… [truncated middle] …\n"
EVIDENCE_EVENTS = 3
EVIDENCE_OUTPUT_CHARS = 300
EVIDENCE_HEADER = "Most recent tool calls (from the trajectory, not the agent's summary):"


# ── Views ─────────────────────────────────────────────────────────────


def view_head4k(text: str) -> str:
    """Production behaviour: keep the first 4,000 characters."""
    return hg._truncate(text, RESPONSE_CHARS)


def view_headtail4k(text: str) -> str:
    """Same budget as production, split between the start and the end of the response."""
    if len(text) <= RESPONSE_CHARS:
        return text
    half = RESPONSE_CHARS // 2
    return text[:half] + HEADTAIL_MARKER + text[-half:]


def render_tool_events(events: Sequence[ToolEvent]) -> str:
    lines = []
    for ev in list(events)[-EVIDENCE_EVENTS:]:
        out = ev.out_tail[-EVIDENCE_OUTPUT_CHARS:].replace("\n", " ").strip()
        lines.append(f"- {ev.tool}: {ev.cmd} → exit {ev.exit} | {out}")
    return "\n".join(lines)


def view_evidence(text: str, events: Sequence[ToolEvent]) -> str:
    """Head-plus-tail response followed by the agent's last tool calls and exit codes."""
    body = view_headtail4k(text)
    block = render_tool_events(events)
    if not block:
        return body
    return (
        f"{body}\n\nMost recent tool calls (from the trajectory, not the agent's summary):\n{block}"
    )


def apply_view(view: str, boundary: BoundaryRecord) -> str:
    text = boundary.last_response
    if view == "head4k":
        return view_head4k(text)
    if view == "headtail4k":
        return view_headtail4k(text)
    if view == "evidence":
        return view_evidence(text, boundary.recent_tool_events)
    raise ValueError(f"unknown view {view!r}")


# ── Prompt construction ───────────────────────────────────────────────


def format_time(now: datetime) -> str:
    if now.tzinfo is None:
        raise ValueError("judge time must be timezone-aware")
    return safe_strftime(now, TIME_FORMAT)


def render_background_block(
    background_processes: Sequence[dict[str, Any]] = (), active_delegations: int = 0
) -> str:
    """Same composition as ``judge_goal``: running processes, then live delegations."""
    block = hg._render_background_block(list(background_processes))
    if active_delegations > 0:
        block += hg.JUDGE_DELEGATIONS_BLOCK_TEMPLATE.format(count=active_delegations)
    return block


def build_user_prompt(
    goal: str,
    response_view: str,
    *,
    prompt: str,
    now: datetime,
    contract: dict[str, str] | None = None,
    background_processes: Sequence[dict[str, Any]] = (),
    active_delegations: int = 0,
) -> str:
    common = dict(
        goal=hg._truncate(goal, GOAL_CHARS),
        response=response_view,
        background_block=render_background_block(background_processes, active_delegations),
        current_time=format_time(now),
    )
    if prompt == "prod-plain":
        return hg.JUDGE_USER_PROMPT_TEMPLATE.format(**common)
    if prompt == "prod-contract":
        block = hg.GoalContract.from_dict(contract).render_block()
        if not block:
            raise ValueError("prod-contract needs a non-empty contract")
        return hg.JUDGE_USER_PROMPT_WITH_CONTRACT_TEMPLATE.format(
            contract_block=hg._truncate(block, CONTRACT_CHARS), **common
        )
    raise ValueError(f"unknown prompt {prompt!r}")


def build_messages(boundary: BoundaryRecord, *, prompt: str, view: str) -> list[dict[str, str]]:
    user = build_user_prompt(
        boundary.goal,
        apply_view(view, boundary),
        prompt=prompt,
        now=boundary.ts,
        contract=boundary.contract,
        background_processes=boundary.background_processes,
        active_delegations=boundary.active_delegations,
    )
    return [
        {"role": "system", "content": hg.JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def prompt_sha256(messages: list[dict[str, str]]) -> str:
    blob = json.dumps(messages, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ── Verdicts ──────────────────────────────────────────────────────────


VERDICTS = ("done", "blocked", "continue", "wait")

# Replies Hermes accepts without flagging ``parse_failed`` but that break the verdict contract in
# JUDGE_SYSTEM_PROMPT. Production treats each as CONTINUE; we keep that and record the kind.
UNKNOWN_LABEL = "unknown_label"  # {"verdict": "finished"}
MISSING_VERDICT = "missing_verdict"  # JSON object with neither "verdict" nor legacy "done"
WAIT_WITHOUT_TARGET = "wait_without_target"  # wait with no session, pid or seconds


@dataclass(frozen=True)
class ParsedVerdict:
    verdict: str  # done | continue | blocked | wait, after Hermes's own fallbacks
    reason: str
    parse_failed: bool
    format_violation: str | None = None

    @property
    def outcome(self) -> str:
        if self.parse_failed:
            return "parse_failed"
        if self.format_violation:
            return "format_violation"
        return "parsed"

    @property
    def decision(self) -> str:
        """Collapse to the three classes scored against truth. Wait parks the loop: not done."""
        return "continue" if self.verdict == "wait" else self.verdict


def _format_violation(raw: str, verdict: str) -> str | None:
    data = hg._extract_json_object(raw)
    if data is None:
        return None
    label = data.get("verdict")
    if isinstance(label, str):
        norm = label.strip().lower()
        if norm not in VERDICTS:
            return UNKNOWN_LABEL
        if norm == "wait" and verdict != "wait":
            return WAIT_WITHOUT_TARGET
        return None
    if "done" not in data:
        return MISSING_VERDICT
    return None


def parse_verdict(raw: str) -> ParsedVerdict:
    """Hermes's parser, unchanged, plus a flag for replies it silently coerces to CONTINUE."""
    verdict, reason, parse_failed, _wait = hg._parse_judge_response(raw)
    violation = None if parse_failed else _format_violation(raw, verdict)
    return ParsedVerdict(verdict, reason, parse_failed, violation)


@dataclass(frozen=True)
class Variant:
    prompt: str
    model: str
    view: str

    @classmethod
    def parse(cls, spec: str) -> Variant:
        try:
            prompt, model, view = spec.split(":")
        except ValueError:
            raise ValueError(f"variant must be prompt:model:view, got {spec!r}") from None
        if prompt not in PROMPTS:
            raise ValueError(f"unknown prompt {prompt!r}")
        if view not in VIEWS:
            raise ValueError(f"unknown view {view!r}")
        return cls(prompt, model, view)

    def __str__(self) -> str:
        return f"{self.prompt}:{self.model}:{self.view}"


Completion = Callable[[list[dict[str, str]]], "CompletionResult"]


@dataclass(frozen=True)
class CompletionResult:
    text: str
    model_reported: str = ""
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
