"""Replay judge variants over frozen boundaries. Resume-safe: reruns skip finished samples.

Output layout under ``results/runs/<run_id>/``::

    judge/<prompt>__<model>__<view>.jsonl   one JudgeVerdict per (boundary, sample)
    errors.jsonl                             calls that still failed after retries
    manifest.json
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

from hjr import judge
from hjr.judge import Completion, CompletionResult, Variant
from hjr.schemas import BoundaryRecord, JudgeVerdict

log = logging.getLogger(__name__)

EMPTY_RESPONSE_REASON = "empty response (nothing to evaluate)"


def verdict_path(run_dir: Path, variant: Variant) -> Path:
    # Colons are not portable in file names.
    return run_dir / "judge" / f"{variant.prompt}__{variant.model}__{variant.view}.jsonl"


def _finished(path: Path) -> set[tuple[str, int]]:
    if not path.exists():
        return set()
    done = set()
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rec = json.loads(line)
                done.add((rec["boundary_id"], rec["sample"]))
    return done


def judge_once(
    boundary: BoundaryRecord,
    variant: Variant,
    sample: int,
    complete: Completion,
    judge_model_id: str,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> JudgeVerdict:
    messages = judge.build_messages(boundary, prompt=variant.prompt, view=variant.view)
    if not boundary.last_response.strip():
        # judge_goal short-circuits before calling the model.
        result = CompletionResult(text="")
        parsed = judge.ParsedVerdict("continue", EMPTY_RESPONSE_REASON, parse_failed=False)
    else:
        result = complete(messages)
        parsed = judge.parse_verdict(result.text)
    return JudgeVerdict(
        boundary_id=boundary.boundary_id,
        variant=str(variant),
        sample=sample,
        verdict=parsed.verdict,
        decision=parsed.decision,
        reason=parsed.reason,
        parse_failed=parsed.parse_failed,
        raw=result.text,
        judge_model=judge_model_id,
        judge_model_reported=result.model_reported,
        prompt_sha256=judge.prompt_sha256(messages),
        latency_ms=result.latency_ms,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        ts=now(),
    )


def replay(
    boundaries: Iterable[BoundaryRecord],
    variants: Iterable[Variant],
    *,
    samples: int,
    run_dir: Path,
    completions: Mapping[str, Completion],
    model_ids: Mapping[str, str],
    workers: int = 8,
) -> Counter[str]:
    """Judge every (boundary, variant, sample) not already on disk. Returns outcome counts."""
    boundaries = list(boundaries)
    counts: Counter[str] = Counter()
    errors_path = run_dir / "errors.jsonl"
    run_dir.mkdir(parents=True, exist_ok=True)

    for variant in variants:
        path = verdict_path(run_dir, variant)
        path.parent.mkdir(parents=True, exist_ok=True)
        finished = _finished(path)
        todo = [
            (b, s) for b in boundaries for s in range(samples) if (b.boundary_id, s) not in finished
        ]
        counts["skipped"] += len(boundaries) * samples - len(todo)
        if not todo:
            continue
        log.info("%s: %d calls (%d already done)", variant, len(todo), len(finished))
        complete = completions[variant.model]
        model_id = model_ids[variant.model]
        with (
            ThreadPoolExecutor(max_workers=workers) as pool,
            path.open("a", encoding="utf-8", newline="\n") as out,
            errors_path.open("a", encoding="utf-8", newline="\n") as err,
        ):
            futures = {
                pool.submit(judge_once, b, variant, s, complete, model_id): (b, s) for b, s in todo
            }
            for fut in as_completed(futures):
                b, s = futures[fut]
                try:
                    rec = fut.result()
                except Exception as exc:  # noqa: BLE001 - logged and retried on the next run
                    counts["failed"] += 1
                    err.write(
                        json.dumps(
                            {
                                "boundary_id": b.boundary_id,
                                "variant": str(variant),
                                "sample": s,
                                "error": f"{type(exc).__name__}: {exc}",
                                "ts": datetime.now(UTC).isoformat(),
                            }
                        )
                        + "\n"
                    )
                    continue
                out.write(rec.model_dump_json() + "\n")
                out.flush()
                counts["parse_failed" if rec.parse_failed else "ok"] += 1
    return counts
