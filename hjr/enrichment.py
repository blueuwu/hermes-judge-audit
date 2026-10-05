"""Offline Phase 1b planning and Stage B selection from primary verifier truth, never trajectories.

Only task_id, category, split, boundary_id and phase are read from a frozen boundaries file;
truth comes from its regrade (``data/truth/<stem>.jsonl``, Amendment 1), never from the truth
frozen at ingest. A boundary without a regraded row is an error.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from hjr import regrade

CATEGORIES = ("C2", "C3", "C4")


@dataclass(frozen=True)
class TaskRate:
    task_id: str
    category: str
    split: str
    boundaries: int
    not_done: int
    excluded: int

    @property
    def probability(self) -> float:
        return self.not_done / (self.boundaries + self.excluded)


def _primary_counts(boundaries: Path, phase: str | None = None) -> dict[tuple, Counter]:
    """Primary-truth state counts per C2-C4 (task, category, split)."""
    primary = regrade.primary_rows(boundaries)
    counts: dict[tuple[str, str, str], Counter] = defaultdict(Counter)
    with boundaries.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            record = json.loads(line)
            if phase is not None and record.get("phase", "1a") != phase:
                raise ValueError(f"expected only phase {phase} boundaries")
            row = primary.get(record["boundary_id"])
            if row is None:
                raise ValueError("boundary has no primary truth row")
            task, category, split = (record[k] for k in ("task_id", "category", "split"))
            if category in CATEGORIES:
                counts[(task, category, split)][regrade.primary_verifier(row).truth_state] += 1
    return counts


def task_rates(boundaries: Path, excluded: Path) -> list[TaskRate]:
    counts = _primary_counts(boundaries)
    exclusions = json.loads(excluded.read_text(encoding="utf-8"))
    return [
        TaskRate(
            task,
            category,
            split,
            sum(states.values()),
            states["not_done"],
            sum(e["trial"].startswith(task.removeprefix("hjr/") + "__") for e in exclusions),
        )
        for (task, category, split), states in sorted(counts.items())
    ]


def stage_b_tasks(stage_a: Path) -> list[str]:
    """Amendment 2: the C2-C4 tasks with at least one primary-truth not-done boundary in
    Stage A, as task directory names. Nothing else enters Stage B."""
    counts = _primary_counts(stage_a, phase="1b-enrichment")
    return sorted(task.removeprefix("hjr/") for (task, _, _), s in counts.items() if s["not_done"])


def detection(rate: float, attempts: int) -> float:
    """P(at least one not-done in ``attempts`` independent attempts at a true rate)."""
    if attempts < 1 or not 0 <= rate <= 1:
        raise ValueError("positive attempts and a rate in [0, 1] required")
    return 1 - (1 - rate) ** attempts


def render(rates: list[TaskRate], attempts: int, true_rates: list[float]) -> str:
    lines = [
        "| Task | Category | Split | Boundaries | Not done | Excluded | Not done / attempt |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rates:
        lines.append(
            f"| {r.task_id} | {r.category} | {r.split} | {r.boundaries} | {r.not_done} "
            f"| {r.excluded} | {r.probability:.6f} |"
        )
    lines += [
        "",
        f"| True not-done rate | P(>=1 not done in {attempts} attempts) |",
        "|---|---|",
    ]
    lines += [f"| {p:.0%} | {detection(p, attempts):.6f} |" for p in true_rates]
    return "\n".join(lines)
