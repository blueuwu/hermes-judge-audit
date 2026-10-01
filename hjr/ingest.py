"""Turn a Harbor job into frozen BoundaryRecords.

Each trial dir holds the harness's ``agent/turns.jsonl`` (what the judge saw, what it said) and
the verifier's ``verifier/boundaries.json`` (the truth for the same workspace snapshots). A
boundary is kept only when both sides exist; every trial or boundary that is dropped is listed
with its reason, as the analysis rules require.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from hjr.schemas import (
    BoundaryRecord,
    ControllerVerdict,
    Split,
    ToolEvent,
    TurnRecord,
    VerifierResult,
    read_jsonl,
)

# Tool use that reaches past the model endpoint. Local runs cannot enforce the allowlist, so
# these boundaries are tagged rather than trusted silently.
NETWORK_USE = re.compile(r"\b(curl|wget|pip3? install|uv (pip|add)|apt(-get)? install|git clone)\b")


@dataclass
class IngestResult:
    boundaries: list[BoundaryRecord] = field(default_factory=list)
    excluded: list[dict[str, str]] = field(default_factory=list)


def _task_meta(tasks_dir: Path, task_id: str) -> dict:
    toml = tasks_dir / task_id.removeprefix("hjr/") / "task.toml"
    return tomllib.loads(toml.read_text(encoding="utf-8"))["metadata"]


def uses_network(events: list[ToolEvent]) -> bool:
    return any(NETWORK_USE.search(e.cmd) for e in events)


def _boundary(
    turn: TurnRecord, truth: dict, meta: dict, *, split: Split, hermes_sha: str, harbor: str
) -> BoundaryRecord:
    controller = turn.controller
    tags: dict[str, str | int | float] = {
        "action": turn.action or "",
        "agent_arm": turn.agent_arm,
        "trial": turn.trial,
        "tool_calls_total": turn.tool_calls_total,
        "agent_seconds": turn.agent_seconds,
        "network_tool_use": int(uses_network(turn.recent_tool_events)),
    }
    if turn.last_response_kind:
        tags["last_response_kind"] = turn.last_response_kind
    if turn.agent_exit_code is not None:
        tags["agent_exit_code"] = turn.agent_exit_code
    if turn.controller_error:
        tags["controller_error"] = turn.controller_error[:200]
    return BoundaryRecord(
        boundary_id=turn.boundary_id,
        run_id=turn.run_id,
        task_id=turn.task_id,
        task_version=meta.get("version", "1.0.0"),
        category=meta["category"],
        split=split,
        agent_model=turn.agent_model,
        turn=turn.turn,
        goal=turn.goal,
        contract=turn.contract,
        last_response=turn.last_response,
        response_chars=turn.response_chars,
        recent_tool_events=turn.recent_tool_events,
        background_processes=turn.background_processes,
        active_delegations=turn.active_delegations,
        controller_verdict=ControllerVerdict(
            verdict=controller.verdict, reason=controller.reason, judge=controller.variant
        )
        if controller
        else None,
        verifier=VerifierResult(
            truth_state=truth["truth_state"], requirements=truth["requirements"]
        ),
        tags=tags,
        hermes_sha=hermes_sha,
        harbor_version=harbor,
        ts=turn.ts,
    )


def ingest_trial(
    trial_dir: Path, tasks_dir: Path, *, split: Split, hermes_sha: str, harbor: str
) -> IngestResult:
    out = IngestResult()
    name = trial_dir.name
    turns_path = trial_dir / "agent" / "turns.jsonl"
    graded_path = trial_dir / "verifier" / "boundaries.json"
    if not turns_path.is_file():
        out.excluded.append(
            {"trial": name, "reason": "no turns.jsonl (agent never finished a turn)"}
        )
        return out
    if not graded_path.is_file():
        out.excluded.append({"trial": name, "reason": "no verifier boundaries.json"})
        return out
    graded = {
        b["snapshot"]: b for b in json.loads(graded_path.read_text(encoding="utf-8"))["boundaries"]
    }
    for turn in read_jsonl(turns_path, TurnRecord):
        truth = graded.get(turn.snapshot)
        if truth is None:
            out.excluded.append({"trial": name, "reason": f"snapshot {turn.snapshot} not graded"})
            continue
        if turn.past_stop:
            out.excluded.append(
                {"trial": name, "reason": f"turn {turn.turn} ran past a production stop (soak)"}
            )
            continue
        if turn.action is None:
            out.excluded.append({"trial": name, "reason": f"turn {turn.turn} has no action"})
            continue
        meta = _task_meta(tasks_dir, turn.task_id)
        out.boundaries.append(
            _boundary(turn, truth, meta, split=split, hermes_sha=hermes_sha, harbor=harbor)
        )
    return out


def ingest_job(
    job_dir: Path, tasks_dir: Path, *, split: Split, hermes_sha: str, harbor: str
) -> IngestResult:
    total = IngestResult()
    for trial_dir in sorted(p for p in job_dir.iterdir() if p.is_dir() and "__" in p.name):
        part = ingest_trial(trial_dir, tasks_dir, split=split, hermes_sha=hermes_sha, harbor=harbor)
        total.boundaries += part.boundaries
        total.excluded += part.excluded
    return total
