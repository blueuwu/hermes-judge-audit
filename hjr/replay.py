"""Replay judge variants over frozen boundaries. Resume-safe: reruns only fill in missing samples.

Output layout under ``results/runs/<run_id>/``::

    judge/<prompt>__<model>__<view>.jsonl   one JudgeVerdict per answered (boundary, sample)
    attempts.jsonl                           every HTTP attempt, including retries and failures
    incidents.jsonl                          provider-reported identity changes (arm halted)
    halts.jsonl                              arms a client stopped (CLI harness violation, quota)
    manifest.json

A call that still fails after retries leaves no verdict, so the next run retries it. If the
provider-reported model or provider changes within an arm, new calls for that arm stop at once,
completed records are kept under their own sub-arm id, and the incident is logged. An arm with
a logged incident is not called again in the same run.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from hjr import judge
from hjr.arms import Arm, sub_arm_id
from hjr.client import CompletionResult, TransportError
from hjr.judge import Variant
from hjr.schemas import AttemptRecord, BoundaryRecord, DriftIncident, JudgeVerdict, read_jsonl

log = logging.getLogger(__name__)

EMPTY_RESPONSE_REASON = "empty response (nothing to evaluate)"

Completion = Callable[[list[dict[str, str]]], CompletionResult]


def verdict_path(run_dir: Path, variant: Variant) -> Path:
    # Colons are not portable in file names.
    return run_dir / "judge" / f"{variant.prompt}__{variant.model}__{variant.view}.jsonl"


def load_verdicts(run_dir: Path) -> list[JudgeVerdict]:
    out: list[JudgeVerdict] = []
    for path in sorted((run_dir / "judge").glob("*.jsonl")):
        out.extend(read_jsonl(path, JudgeVerdict))
    return out


def _now() -> datetime:
    return datetime.now(UTC)


class ArmHalted(RuntimeError):
    pass


@dataclass
class _ArmState:
    """Expected provider-reported identity for one arm, shared across its variants."""

    expected: tuple[str, str] | None
    halted: threading.Event
    lock: threading.Lock


def judge_once(
    boundary: judge.JudgeInput,
    variant: Variant,
    sample: int,
    arm: Arm,
    complete: Completion,
    build_messages: Callable | None = None,
) -> tuple[JudgeVerdict, tuple]:
    builder = build_messages or judge.build_messages
    messages = builder(boundary, prompt=variant.prompt, view=variant.view)
    if not boundary.last_response.strip():
        # judge_goal returns CONTINUE without calling the model.
        result = CompletionResult(text="")
        parsed = judge.ParsedVerdict("continue", EMPTY_RESPONSE_REASON, parse_failed=False)
        outcome, sub = "no_call", ""
    else:
        result = complete(messages)
        parsed = judge.parse_verdict(result.text)
        outcome = parsed.outcome
        sub = sub_arm_id(arm.arm_id, result.model_reported, result.provider_reported)
    rec = JudgeVerdict(
        boundary_id=boundary.boundary_id,
        variant=str(variant),
        sample=sample,
        arm_id=arm.arm_id,
        sub_arm_id=sub,
        outcome=outcome,
        verdict=parsed.verdict,
        decision=parsed.decision,
        reason=parsed.reason,
        parse_failed=parsed.parse_failed,
        format_violation=parsed.format_violation,
        raw=result.text,
        finish_reason=result.finish_reason,
        judge_model=arm.model_id,
        judge_model_reported=result.model_reported,
        provider_reported=result.provider_reported,
        prompt_sha256=judge.prompt_sha256(messages),
        attempts=len(result.attempts) or (0 if outcome == "no_call" else 1),
        latency_ms=result.latency_ms,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        reasoning_tokens=result.reasoning_tokens,
        cached_tokens=result.cached_tokens,
        cost_usd=result.cost_usd,
        harness_meta=result.meta or None,
        ts=_now(),
    )
    return rec, result.attempts


class _Writer:
    """Serialises appends from worker threads; one handle per file."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._handles: dict[Path, object] = {}

    def write(self, path: Path, line: str) -> None:
        with self._lock:
            fh = self._handles.get(path)
            if fh is None:
                path.parent.mkdir(parents=True, exist_ok=True)
                fh = path.open("a", encoding="utf-8", newline="\n")
                self._handles[path] = fh
            fh.write(line + "\n")
            fh.flush()

    def close(self) -> None:
        for fh in self._handles.values():
            fh.close()


def require_repair_open(boundaries: Iterable[BoundaryRecord], variants: Iterable[Variant]) -> None:
    """repair-v1 is designed on dev material; no held-out boundary reaches it before the freeze
    (prereg Amendment 3)."""
    from hjr.pools import HELDOUT_TAG, judge_unsealed

    if not any(v.prompt == "repair-v1" for v in variants):
        return
    if any(b.split != "dev" for b in boundaries) and not judge_unsealed():
        raise PermissionError(
            f"repair-v1 on held-out boundaries needs tag {HELDOUT_TAG} as an ancestor of HEAD"
        )


def _identity(rec: JudgeVerdict) -> tuple[str, str]:
    return rec.judge_model_reported, rec.provider_reported


def replay(
    boundaries: Iterable[BoundaryRecord],
    variants: Iterable[Variant],
    *,
    samples: int,
    run_dir: Path,
    arms: Mapping[str, Arm],
    completions: Mapping[str, Completion],
    workers: int = 8,
    build_messages: Callable | None = None,
) -> Counter[str]:
    """Judge every (boundary, variant, sample) not already on disk. Returns outcome counts."""
    boundaries = list(boundaries)
    variants = list(variants)
    require_repair_open(boundaries, variants)
    run_dir.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    writer = _Writer()
    attempts_path = run_dir / "attempts.jsonl"
    incidents_path = run_dir / "incidents.jsonl"

    existing = load_verdicts(run_dir)
    halted_before = {
        i.arm_id
        for i in (read_jsonl(incidents_path, DriftIncident) if incidents_path.exists() else [])
    }
    states: dict[str, _ArmState] = {}
    for key, arm in arms.items():
        prior = [r for r in existing if r.arm_id == arm.arm_id and r.outcome != "no_call"]
        expected = _identity(min(prior, key=lambda r: r.ts)) if prior else None
        state = _ArmState(expected, threading.Event(), threading.Lock())
        if arm.arm_id in halted_before:
            state.halted.set()
        states[key] = state
    finished = {(r.variant, r.boundary_id, r.sample) for r in existing}

    def task(b: BoundaryRecord, v: Variant, s: int):
        if states[v.model].halted.is_set():
            raise ArmHalted(v.model)
        rec, attempts = judge_once(
            b, v, s, arms[v.model], completions[v.model], build_messages=build_messages
        )
        # Checked in the worker, so the halt takes effect before the next queued call starts.
        return rec, attempts, check_identity(rec, v)

    def log_attempts(b: BoundaryRecord, v: Variant, s: int, attempts) -> None:
        for a in attempts:
            writer.write(
                attempts_path,
                AttemptRecord(
                    boundary_id=b.boundary_id,
                    variant=str(v),
                    sample=s,
                    arm_id=arms[v.model].arm_id,
                    attempt=a.attempt,
                    status="ok" if a.ok else "error",
                    error_type=a.error_type,
                    http_status=a.http_status,
                    retryable=a.retryable,
                    latency_ms=a.latency_ms,
                    ts=_now(),
                ).model_dump_json(exclude_none=True),
            )

    def check_identity(rec: JudgeVerdict, v: Variant) -> DriftIncident | None:
        if rec.outcome == "no_call":
            return None
        state = states[v.model]
        with state.lock:
            if state.expected is None:
                state.expected = _identity(rec)
                return None
            if _identity(rec) == state.expected or state.halted.is_set():
                return None
            state.halted.set()
        log.error("identity changed for arm %s (%s); halting it", v.model, rec.arm_id)
        names = ("model", "provider")
        return DriftIncident(
            run_id=run_dir.name,
            arm_id=rec.arm_id,
            expected=dict(zip(names, state.expected, strict=True)),
            observed=dict(zip(names, _identity(rec), strict=True)),
            boundary_id=rec.boundary_id,
            variant=rec.variant,
            sample=rec.sample,
            ts=_now(),
        )

    todo = [
        (b, v, s)
        for v in variants
        for b in boundaries
        for s in range(samples)
        if (str(v), b.boundary_id, s) not in finished
    ]
    counts["skipped"] = len(boundaries) * len(variants) * samples - len(todo)
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(task, *job): job for job in todo}
            for fut in as_completed(futures):
                b, v, s = futures[fut]
                try:
                    rec, attempts, incident = fut.result()
                except ArmHalted as exc:
                    # Raised by the replay itself, or by a client that cannot go on (a CLI
                    # harness violation, an exhausted quota). Either way the arm stops here.
                    if not states[v.model].halted.is_set():
                        states[v.model].halted.set()
                        log.error("arm %s halted: %s", v.model, exc)
                        halt = {"arm": v.model, "variant": str(v), "reason": str(exc)}
                        writer.write(
                            run_dir / "halts.jsonl",
                            json.dumps(halt | {"ts": _now().isoformat()}),
                        )
                    counts["halted"] += 1
                    continue
                except TransportError as exc:
                    log_attempts(b, v, s, exc.attempts)
                    counts["transport_failed"] += 1
                    continue
                log_attempts(b, v, s, attempts)
                writer.write(verdict_path(run_dir, v), rec.model_dump_json(exclude_none=True))
                counts[rec.outcome] += 1
                if incident is not None:
                    writer.write(incidents_path, incident.model_dump_json())
                    counts["drift_incidents"] += 1
    finally:
        writer.close()
    return counts


def reparse(run_dir: Path, out_dir: Path) -> Counter[str]:
    """Re-parse stored raw responses with the current parser; never touches the originals.

    Writes ``out_dir/judge/*.jsonl`` and returns how many records changed outcome or decision.
    """
    counts: Counter[str] = Counter()
    for path in sorted((run_dir / "judge").glob("*.jsonl")):
        rows = []
        for rec in read_jsonl(path, JudgeVerdict):
            counts["records"] += 1
            if rec.outcome == "no_call":
                rows.append(rec)
                continue
            parsed = judge.parse_verdict(rec.raw)
            new = rec.model_copy(
                update={
                    "outcome": parsed.outcome,
                    "verdict": parsed.verdict,
                    "decision": parsed.decision,
                    "reason": parsed.reason,
                    "parse_failed": parsed.parse_failed,
                    "format_violation": parsed.format_violation,
                }
            )
            counts["outcome_changed"] += new.outcome != rec.outcome
            counts["decision_changed"] += new.decision != rec.decision
            rows.append(new)
        target = out_dir / "judge" / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="\n") as fh:
            for r in rows:
                fh.write(r.model_dump_json(exclude_none=True) + "\n")
    return counts
