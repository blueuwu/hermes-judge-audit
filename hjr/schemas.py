"""Record types for every JSONL file the audit writes. One line = one model instance."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

TruthState = Literal["done", "not_done", "blocked"]
# "probe" items test output-format compliance only and never enter a semantic metric.
Split = Literal["dev", "heldout", "probe"]
Phase = Literal["1a", "1b-enrichment"]


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ToolEvent(_Record):
    tool: str
    cmd: str
    exit: int | None = None
    out_tail: str = ""


class VerifierResult(_Record):
    truth_state: TruthState
    requirements: dict[str, bool] = Field(default_factory=dict)
    # "verifier": graded from a workspace snapshot; "constructed": fixed by item design.
    source: Literal["verifier", "constructed"] = "verifier"


class ControllerVerdict(_Record):
    verdict: str
    reason: str
    judge: str


class BoundaryRecord(_Record):
    """One judge decision point: a turn boundary in a trial, or a constructed item."""

    boundary_id: str
    run_id: str
    task_id: str
    # Omit the legacy default on serialization to preserve constructed fixture hashes.
    phase: Phase = Field(default="1a", exclude_if=lambda value: value == "1a")
    task_version: str = "1.0.0"
    category: str
    split: Split
    agent_model: str | None = None
    rep: int | None = None
    turn: int | None = None
    goal: str
    contract: dict[str, str] | None = None
    last_response: str
    response_chars: int
    recent_tool_events: list[ToolEvent] = Field(default_factory=list)
    # As gathered by Hermes for the judge prompt; empty for nearly every boundary.
    background_processes: list[dict[str, Any]] = Field(default_factory=list)
    active_delegations: int = 0
    controller_verdict: ControllerVerdict | None = None
    verifier: VerifierResult
    tags: dict[str, str | int | float] = Field(default_factory=dict)
    hermes_sha: str
    harbor_version: str | None = None
    ts: AwareDatetime


class JudgeVerdict(_Record):
    """One judge call that returned a response. Transport failures never become a verdict;
    they are logged as AttemptRecords and the call is retried on the next run."""

    boundary_id: str
    variant: str
    sample: int
    arm_id: str
    # Arm plus the identity the provider reported; empty when no model call was made.
    sub_arm_id: str
    # parsed | parse_failed | format_violation | no_call (Hermes skips empty responses)
    outcome: Literal["parsed", "parse_failed", "format_violation", "no_call"]
    verdict: str
    decision: Literal["done", "continue", "blocked"]
    reason: str
    parse_failed: bool
    format_violation: str | None = None
    raw: str
    finish_reason: str = ""
    judge_model: str
    judge_model_reported: str = ""
    provider_reported: str = ""
    prompt_sha256: str
    attempts: int = 1
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float | None = None
    # Serving metadata without a field of its own, e.g. the Codex CLI session id and version
    harness_meta: dict[str, str] | None = None
    ts: AwareDatetime


class TurnRecord(_Record):
    """One turn boundary as the harness saw it, before verification. Ingest joins it with the
    verifier's grade of the same workspace snapshot to make a BoundaryRecord."""

    boundary_id: str
    run_id: str
    trial: str
    task_id: str
    agent_arm: str
    agent_model: str
    turn: int
    prompt: str  # what the harness sent this turn
    goal: str
    contract: dict[str, str] | None = None
    last_response: str
    last_response_kind: str = ""  # display_kind; "failed_turn" is Hermes's failure notice
    response_chars: int
    # Hermes's estimate of the turn's last request: system prompt, tool schemas, history
    context_tokens_est: int = 0
    session_id: str | None
    recent_tool_events: list[ToolEvent] = Field(default_factory=list)  # this turn's calls
    tool_calls_total: int = 0  # whole session so far
    # What the judge was shown. Production lists Hermes-managed background processes; the
    # harness passes none and records what was actually running instead.
    background_processes: list[dict[str, Any]] = Field(default_factory=list)
    processes_running: list[str] = Field(default_factory=list)
    active_delegations: int = 0
    snapshot: str
    # The in-loop judge call (production prompt, self judge, head4k). None until the judge
    # answers, and for good when it never returns; production then continues.
    controller: JudgeVerdict | None = None
    controller_error: str = ""
    # What the loop did next; None only on the pending record the judge is shown.
    action: (
        Literal[
            "done",
            "blocked",
            "continue",
            "pause_parse",
            "pause_transport",
            "budget",
            "empty_response",
        ]
        | None
    ) = None
    agent_exit_code: int | None = None
    agent_seconds: float = 0.0
    # Soak only: production would already have ended the goal. Never analysed.
    past_stop: bool = False
    ts: AwareDatetime


class AttemptRecord(_Record):
    """Every HTTP attempt, successful or not. Transport reliability is computed from these."""

    boundary_id: str
    variant: str
    sample: int
    arm_id: str
    attempt: int
    status: Literal["ok", "error"]
    error_type: str = ""
    http_status: int | None = None
    retryable: bool = False
    latency_ms: int = 0
    ts: AwareDatetime


class DriftIncident(_Record):
    """The provider-reported identity changed within an arm; the arm was halted."""

    run_id: str
    arm_id: str
    expected: dict[str, str]
    observed: dict[str, str]
    boundary_id: str
    variant: str
    sample: int
    ts: AwareDatetime


class RunManifest(_Record):
    run_id: str
    kind: Literal["judge-replay", "harbor"]
    phase: Phase = Field(default="1a", exclude_if=lambda value: value == "1a")
    git_sha: str
    git_dirty: bool
    hermes_sha: str
    uv_lock_sha256: str
    inputs: dict[str, str]  # path -> sha256
    variants: list[str]
    samples: int
    judge_config_sha256: str
    # Arm key -> identity, arm_id, model source and any substitution note.
    models: dict[str, dict[str, str]]
    # arm_id -> each provider-reported (model, provider) seen, with its sub_arm_id and count.
    observed_identities: dict[str, list[dict[str, str | int]]] = Field(default_factory=dict)
    seed: int
    started_at: datetime
    finished_at: datetime | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    usage: dict[str, dict[str, float]] = Field(default_factory=dict)
    notes: str = ""


def read_jsonl[M: BaseModel](path: Path, model: type[M]) -> Iterator[M]:
    with path.open(encoding="utf-8") as fh:
        for n, line in enumerate(fh, start=1):
            if line.strip():
                try:
                    yield model.model_validate_json(line)
                except ValueError as exc:
                    raise ValueError(f"{path}:{n}: {exc}") from exc


def write_jsonl(path: Path, records: Iterable[BaseModel]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for rec in records:
            fh.write(rec.model_dump_json(exclude_none=True) + "\n")
            count += 1
    return count


def require_single_phase(records: Iterable) -> Phase:
    phases = {r.phase for r in records}
    if len(phases) > 1:
        raise ValueError(f"refusing to mix phases: {sorted(phases)}")
    return next(iter(phases), "1a")
