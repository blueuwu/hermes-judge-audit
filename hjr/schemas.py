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
    boundary_id: str
    variant: str
    sample: int
    verdict: str
    decision: Literal["done", "continue", "blocked"]
    reason: str
    parse_failed: bool
    transport_failed: bool = False
    raw: str
    judge_model: str
    judge_model_reported: str = ""
    prompt_sha256: str
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    ts: AwareDatetime


class RunManifest(_Record):
    run_id: str
    kind: Literal["judge-replay", "harbor"]
    git_sha: str
    git_dirty: bool
    hermes_sha: str
    uv_lock_sha256: str
    inputs: dict[str, str]  # path -> sha256
    variants: list[str]
    samples: int
    judge_config_sha256: str
    models: dict[str, dict[str, str]]
    seed: int
    started_at: datetime
    finished_at: datetime | None = None
    counts: dict[str, int] = Field(default_factory=dict)
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
