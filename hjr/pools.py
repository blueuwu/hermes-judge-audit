"""Phase 1b reported pools (the note's analysis rules and deviation-2).

A pool is the set of boundaries one reported figure is computed over, for example Stage A on
all tasks, or Stage A+B on the selected tasks, either one restricted to dev only. Every pool is
gated on its own:

* Fewer than ``MIN_NOT_DONE_TASKS`` distinct tasks with a primary-truth not-done boundary in the
  pool: per-task counts only, with no pooled rate or interval.
* Otherwise micro (boundary-weighted) and task-macro (task-weighted) estimates, each with a
  task-bootstrap interval. The clusters are the tasks that contribute boundaries to the figure,
  so a not-done rate clusters over every task in the pool, zero-not-done tasks included, while a
  judge metric conditioned on truth clusters over the tasks with boundaries in that condition.
  With ``COARSE_MAX_CLUSTERS`` or fewer clusters the intervals are labelled coarse, with the
  cluster count.

Held-out-only and pooled figures that include held-out boundaries are sealed until
``repair-freeze-v1``; a pool holding any held-out row is refused before anything is computed.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from hjr import audit, stats

MIN_NOT_DONE_TASKS = 5
# Task-bootstrap intervals over this many clusters or fewer are reported as coarse.
COARSE_MAX_CLUSTERS = 10


class Row(Protocol):
    @property
    def task_id(self) -> str: ...
    @property
    def split(self) -> str: ...
    @property
    def truth(self) -> str: ...


@dataclass(frozen=True)
class PoolFigure:
    pool: str
    figure: str
    k: int
    n: int
    # Tasks contributing boundaries to this figure: the bootstrap clusters
    clusters: int
    # Distinct tasks with a not-done boundary anywhere in the pool: the gate
    not_done_tasks: int
    per_task: tuple[tuple[str, int, int], ...]  # (task, k, n)
    micro: stats.BootstrapCI | None
    macro: stats.BootstrapCI | None

    @property
    def counts_only(self) -> bool:
        return self.not_done_tasks < MIN_NOT_DONE_TASKS

    @property
    def coarse(self) -> bool:
        return not self.counts_only and self.clusters <= COARSE_MAX_CLUSTERS


def require_unsealed(rows: Sequence[Row]) -> None:
    for split in sorted({r.split for r in rows}):
        audit.require_open(split)


def not_done_tasks(rows: Sequence[Row]) -> int:
    return len({r.task_id for r in rows if r.truth == "not_done"})


def figure[R: Row](
    pool: str,
    rows: Sequence[R],
    name: str,
    hit: Callable[[R], bool],
    *,
    seed: str,
    given: Callable[[R], bool] = lambda r: True,
) -> PoolFigure:
    """Share of ``hit`` among the pool rows passing ``given``, gated on the whole pool."""
    require_unsealed(rows)
    gate = not_done_tasks(rows)
    subset = [r for r in rows if given(r)]
    tasks: dict[str, list[bool]] = defaultdict(list)
    for r in subset:
        tasks[r.task_id].append(bool(hit(r)))
    per_task = tuple((t, sum(v), len(v)) for t, v in sorted(tasks.items()))
    k = sum(x for _, x, _ in per_task)
    micro = macro = None
    if gate >= MIN_NOT_DONE_TASKS and subset:
        key = f"{seed}:{pool}:{name}"
        micro = stats.cluster_bootstrap(
            subset,
            lambda r: r.task_id,
            lambda rs: sum(bool(hit(r)) for r in rs) / len(rs) if rs else None,
            seed=f"{key}:micro",
        )
        macro = stats.task_macro_bootstrap(
            subset, lambda r: r.task_id, lambda r: float(bool(hit(r))), seed=f"{key}:macro"
        )
    return PoolFigure(pool, name, k, len(subset), len(tasks), gate, per_task, micro, macro)


def render(f: PoolFigure) -> list[str]:
    lines = [f"### {f.pool}: {f.figure}", ""]
    if f.counts_only:
        lines.append(
            f"{f.not_done_tasks} distinct tasks with a not-done boundary (fewer than "
            f"{MIN_NOT_DONE_TASKS}): per-task counts only, no pooled rate or interval."
        )
    else:
        note = f", coarse: {f.clusters} task clusters" if f.coarse else ""
        lines += [
            f"{f.k}/{f.n} across {f.clusters} task clusters{note}.",
            "",
            "| Estimate | Value | Task bootstrap 95% |",
            "|---|---|---|",
            f"| Micro | {_ci(f.micro)} |",
            f"| Task-macro | {_ci(f.macro)} |",
        ]
    lines += ["", "| Task | k | n |", "|---|---|---|"]
    lines += [f"| {t} | {k} | {n} |" for t, k, n in f.per_task]
    return lines + [""]


def _ci(ci: stats.BootstrapCI | None) -> str:
    if ci is None or ci.estimate is None:
        return "– | –"
    if ci.low is None:
        return f"{ci.estimate:.4f} | –"
    return f"{ci.estimate:.4f} | [{ci.low:.4f}, {ci.high:.4f}]"
