"""Phase 1b reported pools (the note's analysis rules and deviation-2).

A pool is the set of boundaries one reported figure is computed over, for example Stage A on
all tasks, or Stage A+B on the selected tasks restricted to dev. Every pool is gated on its own:

* Fewer than ``MIN_NOT_DONE_TASKS`` distinct tasks with a primary-truth not-done boundary in the
  pool: per-task counts only. That means raw per-task numerators and denominators, and
  judge-vs-truth contingency counts for judge figures, with no rate, point estimate or interval,
  per task or pooled.
* Otherwise micro (boundary-weighted) and task-macro (task-weighted) estimates, each with a
  task-bootstrap interval that resamples whole tasks. The clusters are the tasks that
  contribute boundaries to the figure, so a not-done rate clusters over every task in the pool,
  zero-not-done tasks included, while a judge metric conditioned on truth clusters over the
  tasks with boundaries in that condition. Every interval carries ``n_clusters`` and
  ``n_clusters_with_events``; with ``COARSE_MAX_CLUSTERS`` or fewer clusters it is coarse.

Truth not-done rates are boundary-level: not-done truth rows over truth-labeled boundaries.
Trials that produced no boundary are counted separately and never enter a denominator.

Sealing (deviation-2, sealing scope): primary-truth counts and rates are unsealed on every
split. Any figure derived from judge outputs on a pool holding a row outside dev is refused
until the tag ``repair-freeze-v1`` exists and is an ancestor of the analyzed HEAD. The loaders
read the judge label only for rows of an open pool, and never read judge reasons.
"""

from __future__ import annotations

import json
import subprocess
from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from hjr import regrade, stats
from hjr.audit import HELDOUT_TAG
from hjr.config import ROOT

MIN_NOT_DONE_TASKS = 5
# Task-bootstrap intervals over this many clusters or fewer are reported as coarse.
COARSE_MAX_CLUSTERS = 10
NO_BOUNDARY = ("no turns.jsonl (agent never finished a turn)", "no verifier boundaries.json")
TRUTH_STATES = ("done", "not_done", "blocked")
# The in-loop judge's decision as scored against truth; wait parks the loop, so it continues.
JUDGE_DECISIONS = ("done", "continue", "blocked", "none")

Kind = Literal["truth", "judge"]


class Row(Protocol):
    @property
    def task_id(self) -> str: ...
    @property
    def split(self) -> str: ...
    @property
    def truth(self) -> str: ...


@dataclass(frozen=True)
class Boundary:
    """The fields of a frozen boundary a pool figure may use. ``judge`` is ``None`` unless
    it was loaded for an open pool; "none" means the in-loop judge never answered."""

    boundary_id: str
    task_id: str
    split: str
    truth: str
    judge: str | None = None


@dataclass(frozen=True)
class PoolCI:
    estimate: float | None
    low: float | None
    high: float | None
    resamples: int
    undefined: int
    # Bootstrap task clusters, and those with at least one event of this statistic
    n_clusters: int
    n_clusters_with_events: int

    @property
    def coarse(self) -> bool:
        return self.n_clusters <= COARSE_MAX_CLUSTERS


@dataclass(frozen=True)
class TaskCount:
    task: str
    k: int  # boundaries with the event
    n: int  # boundaries in the figure's condition


@dataclass(frozen=True)
class PoolFigure:
    pool: str
    figure: str
    kind: Kind
    # What one event is, e.g. "a primary-truth not-done boundary"
    event: str
    # Distinct tasks with a not-done boundary anywhere in the pool: the gate
    not_done_tasks: int
    per_task: tuple[TaskCount, ...]
    # Whether pooled estimates were asked for; selected-task stages report per task only
    pooled: bool
    micro: PoolCI | None
    macro: PoolCI | None

    @property
    def counts_only(self) -> bool:
        return self.not_done_tasks < MIN_NOT_DONE_TASKS

    @property
    def n_clusters(self) -> int:
        return len(self.per_task)

    @property
    def n_clusters_with_events(self) -> int:
        return sum(t.k > 0 for t in self.per_task)


# ── Seal ──────────────────────────────────────────────────────────────


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def judge_unsealed(root: Path = ROOT, head: str = "HEAD") -> bool:
    """True only when ``repair-freeze-v1`` exists and is an ancestor of ``head`` (or is it).
    A tag elsewhere in the repository, off the analyzed history, does not unseal."""
    tag = _git(root, "rev-parse", "-q", "--verify", f"refs/tags/{HELDOUT_TAG}^{{commit}}")
    if tag.returncode != 0:
        return False
    return _git(root, "merge-base", "--is-ancestor", tag.stdout.strip(), head).returncode == 0


def sealed_splits(splits: Collection[str]) -> list[str]:
    return sorted(s for s in set(splits) if s != "dev")


def require_judge_open(splits: Collection[str], root: Path = ROOT) -> None:
    sealed = sealed_splits(splits)
    if sealed and not judge_unsealed(root):
        raise PermissionError(
            f"judge-derived figures on a pool with {', '.join(sealed)} rows are sealed until "
            f"{HELDOUT_TAG} is an ancestor of HEAD"
        )


# ── Figures ───────────────────────────────────────────────────────────


def not_done_tasks(rows: Sequence[Row]) -> int:
    return len({r.task_id for r in rows if r.truth == "not_done"})


def figure[R: Row](
    pool: str,
    rows: Sequence[R],
    name: str,
    hit: Callable[[R], bool],
    *,
    kind: Kind,
    event: str,
    seed: str,
    given: Callable[[R], bool] = lambda r: True,
    pooled: bool = True,
    root: Path = ROOT,
) -> PoolFigure:
    """Share of ``hit`` among the pool rows passing ``given``, gated on the whole pool.

    ``n_clusters_with_events`` is the number of tasks contributing rows to the figure with at
    least one row where ``hit`` holds: for a not-done rate, tasks with a not-done boundary; for
    a judge metric conditioned on truth, tasks with a conditioned boundary where the judge made
    the counted decision.
    """
    if kind == "judge":
        require_judge_open({r.split for r in rows}, root)
    gate = not_done_tasks(rows)
    subset = [r for r in rows if given(r)]
    tasks: dict[str, list[bool]] = defaultdict(list)
    for r in subset:
        tasks[r.task_id].append(bool(hit(r)))
    per_task = tuple(TaskCount(t, sum(v), len(v)) for t, v in sorted(tasks.items()))
    micro = macro = None
    if pooled and gate >= MIN_NOT_DONE_TASKS and subset:
        key = f"{seed}:{pool}:{name}"
        clusters = len(per_task), sum(t.k > 0 for t in per_task)
        micro = _with_clusters(
            stats.cluster_bootstrap(
                subset,
                lambda r: r.task_id,
                lambda rs: sum(bool(hit(r)) for r in rs) / len(rs) if rs else None,
                seed=f"{key}:micro",
            ),
            *clusters,
        )
        macro = _with_clusters(
            stats.task_macro_bootstrap(
                subset, lambda r: r.task_id, lambda r: float(bool(hit(r))), seed=f"{key}:macro"
            ),
            *clusters,
        )
    return PoolFigure(pool, name, kind, event, gate, per_task, pooled, micro, macro)


def _with_clusters(ci: stats.BootstrapCI, n: int, with_events: int) -> PoolCI:
    return PoolCI(ci.estimate, ci.low, ci.high, ci.resamples, ci.undefined, n, with_events)


def contingency(rows: Sequence[Boundary], root: Path = ROOT) -> dict[str, Counter[tuple[str, str]]]:
    """Per-task (truth, judge decision) counts: raw counts, permitted on any open pool."""
    require_judge_open({r.split for r in rows}, root)
    out: dict[str, Counter[tuple[str, str]]] = defaultdict(Counter)
    for r in rows:
        if r.judge is None:
            raise ValueError("judge decisions were not loaded for this pool")
        out[r.task_id][(r.truth, r.judge)] += 1
    return dict(sorted(out.items()))


def judge_figures(pool: str, rows: Sequence[Boundary], *, seed: str, root: Path = ROOT):
    """Truth-conditioned in-loop judge metrics. Boundaries the judge never answered are left
    out of both; they stay visible in the contingency counts."""
    answered = [r for r in rows if r.judge not in (None, "none")]
    return [
        figure(
            pool,
            answered,
            "judge done given primary not done",
            lambda r: r.judge == "done",
            kind="judge",
            event="a primary not-done boundary the judge called done",
            given=lambda r: r.truth == "not_done",
            seed=seed,
            root=root,
        ),
        figure(
            pool,
            answered,
            "judge not done given primary done",
            lambda r: r.judge != "done",
            kind="judge",
            event="a primary done boundary the judge did not call done",
            given=lambda r: r.truth == "done",
            seed=seed,
            root=root,
        ),
    ]


# ── Loading (metadata only) ───────────────────────────────────────────


def _decision(doc: dict) -> str:
    verdict = (doc.get("controller_verdict") or {}).get("verdict")
    if verdict is None:
        return "none"
    verdict = str(verdict).strip().lower()
    if verdict == "wait":
        return "continue"
    if verdict not in JUDGE_DECISIONS:
        raise ValueError("unexpected in-loop judge verdict label")
    return verdict


def load(
    path: Path,
    *,
    tasks: Collection[str] | None = None,
    splits: Collection[str] | None = None,
    judge: bool = False,
    phase: str | None = None,
    root: Path = ROOT,
) -> list[Boundary]:
    """Rows of a frozen boundaries file with primary truth (``hjr regrade``). Only ids, task,
    split and, when ``judge`` is set, the verdict label are read; the label only after the
    selected rows are known to form an open pool."""
    primary = regrade.primary_rows(path)
    docs = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            doc = json.loads(line)
            if phase is not None and doc.get("phase", "1a") != phase:
                raise ValueError(f"expected only phase {phase} boundaries")
            if tasks is not None and doc["task_id"] not in tasks:
                continue
            if splits is not None and doc["split"] not in splits:
                continue
            docs.append(doc)
    if judge:
        require_judge_open({d["split"] for d in docs}, root)
    out = []
    for doc in docs:
        row = primary.get(doc["boundary_id"])
        if row is None:
            raise ValueError("boundary has no primary truth row")
        out.append(
            Boundary(
                doc["boundary_id"],
                doc["task_id"],
                doc["split"],
                regrade.primary_verifier(row).truth_state,
                _decision(doc) if judge else None,
            )
        )
    return out


def no_boundary_trials(excluded: Path, tasks: Collection[str]) -> dict[str, Counter[str]]:
    """Excluded trials per task, by reason, from an ingest exclusions file."""
    out: dict[str, Counter[str]] = {t: Counter() for t in tasks}
    for e in json.loads(excluded.read_text(encoding="utf-8")):
        owner = [t for t in tasks if e["trial"].startswith(t.removeprefix("hjr/") + "__")]
        if len(owner) != 1:
            raise ValueError("excluded trial does not belong to exactly one pool task")
        out[owner[0]][e["reason"]] += 1
    return out


# ── Rendering ─────────────────────────────────────────────────────────


def render(f: PoolFigure, rates: bool = True) -> list[str]:
    """Markdown for one figure. ``rates`` False keeps per-task rows to counts, for a pool whose
    per-task rates are reported elsewhere (Stage A on the tasks that Stage B selected)."""
    lines = [f"### {f.pool}: {f.figure}", "", f"Event: {f.event}."]
    lines.append(
        f"Distinct tasks with a primary not-done boundary in the pool: {f.not_done_tasks}."
    )
    if f.counts_only:
        lines += [
            f"Fewer than {MIN_NOT_DONE_TASKS}: per-task counts only, with no rate, point "
            "estimate or interval.",
            "",
            "| Task | Events | Boundaries |",
            "|---|---|---|",
        ]
        lines += [f"| {t.task} | {t.k} | {t.n} |" for t in f.per_task]
        return lines + [""]
    if f.micro is not None and f.macro is not None:
        k, n = sum(t.k for t in f.per_task), sum(t.n for t in f.per_task)
        coarse = "coarse, " if f.micro.coarse else ""
        lines += [
            "",
            f"{k}/{n} boundaries; task bootstrap ({coarse}n_clusters={f.n_clusters}, "
            f"n_clusters_with_events={f.n_clusters_with_events}, "
            f"{f.micro.resamples} resamples).",
            "",
            "| Estimate | Value | Task bootstrap 95% | n_clusters | n_clusters_with_events |",
            "|---|---|---|---|---|",
            f"| Micro | {_ci(f.micro)} |",
            f"| Task-macro | {_ci(f.macro)} |",
        ]
    if not rates:
        lines += ["", "| Task | Events | Boundaries |", "|---|---|---|"]
        lines += [f"| {t.task} | {t.k} | {t.n} |" for t in f.per_task]
        return lines + [""]
    lines += ["", "| Task | Events | Boundaries | Rate |", "|---|---|---|---|"]
    lines += [f"| {t.task} | {t.k} | {t.n} | {t.k / t.n:.4f} |" for t in f.per_task]
    return lines + [""]


def _ci(ci: PoolCI) -> str:
    tail = f"{ci.n_clusters} | {ci.n_clusters_with_events}"
    if ci.estimate is None:
        return f"– | – | {tail}"
    if ci.low is None:
        return f"{ci.estimate:.4f} | – | {tail}"
    return f"{ci.estimate:.4f} | [{ci.low:.4f}, {ci.high:.4f}] | {tail}"


def render_contingency(table: dict[str, Counter[tuple[str, str]]]) -> list[str]:
    head = " | ".join(f"judge {d}" for d in JUDGE_DECISIONS)
    lines = [f"| Task | Primary truth | Boundaries | {head} |", "|---|---|---" + "|---" * 4 + "|"]
    for task, cells in table.items():
        for truth in TRUTH_STATES:
            counts = [cells[(truth, d)] for d in JUDGE_DECISIONS]
            if sum(counts):
                lines.append(
                    f"| {task} | {truth} | {sum(counts)} | {' | '.join(map(str, counts))} |"
                )
    return lines + [""]


def render_trials(trials: dict[str, Counter[str]]) -> list[str]:
    lines = ["| Task | No-boundary trials | Other exclusions |", "|---|---|---|"]
    for task, reasons in sorted(trials.items()):
        none = sum(reasons[r] for r in NO_BOUNDARY)
        lines.append(f"| {task} | {none} | {sum(reasons.values()) - none} |")
    return lines + [""]


# ── Phase 1b report ───────────────────────────────────────────────────

PHASE = "1b-enrichment"
JUDGE_POOLS = {"dev": ("dev",), "heldout": ("heldout",), "all": ("dev", "heldout")}


def _excluded(frozen: Path) -> Path:
    return frozen.with_name(frozen.stem + ".excluded.json")


def report(
    stage_a: Path,
    stage_b: Path,
    judge_pools: Sequence[str],
    *,
    seed: str,
    root: Path = ROOT,
) -> str:
    """The Phase 1b pool report. Every judge pool is checked against the seal before any
    figure is computed, so a refused pool stops the whole report."""
    for name in judge_pools:
        require_judge_open(JUDGE_POOLS[name], root)
    a = load(stage_a, phase=PHASE, root=root)
    b = load(stage_b, phase=PHASE, root=root)
    a_tasks = sorted({r.task_id for r in a})
    selected = sorted({r.task_id for r in b})
    head = _git(root, "rev-parse", "HEAD").stdout.strip()
    lines = [
        "# Phase 1b pool analysis",
        "",
        f"Generated by `hjr phase1b-pools` at commit `{head}`, seed `{seed}`, "
        f"{stats.BOOTSTRAP_RESAMPLES} task-bootstrap resamples, 95% percentile intervals.",
        f"Stage A: `{_rel(stage_a, root)}`, {len(a)} boundaries. "
        f"Stage B: `{_rel(stage_b, root)}`, {len(b)} boundaries.",
        "Truth is primary truth from `hjr regrade`. Rates are boundary-level: not-done truth rows "
        "over truth-labeled boundaries. No-boundary trials are counted separately and are not in "
        "any denominator.",
        "",
        "## Stage A: primary-truth not-done prevalence (uniform sample)",
        "",
        *render(
            figure(
                "Stage A, all tasks",
                a,
                "primary not-done rate",
                lambda r: r.truth == "not_done",
                kind="truth",
                event="a primary-truth not-done boundary",
                seed=seed,
                root=root,
            ),
            rates=False,
        ),
        "Per-task not-done rates on the selected tasks are reported from Stage B only.",
        "",
        "Stage A trials without a boundary:",
        "",
        *render_trials(no_boundary_trials(_excluded(stage_a), a_tasks)),
        "## Stage B: primary-truth not done on the selected tasks",
        "",
        "Selected tasks only, chosen for a Stage A not-done boundary: per-task results, not "
        "prevalence. Stage A+B on these tasks is enrichment yield only.",
        "",
        *render(
            figure(
                "Stage B, selected tasks",
                b,
                "primary not-done rate",
                lambda r: r.truth == "not_done",
                kind="truth",
                event="a primary-truth not-done boundary",
                seed=seed,
                pooled=False,
                root=root,
            )
        ),
        "Stage B trials without a boundary:",
        "",
        *render_trials(no_boundary_trials(_excluded(stage_b), selected)),
    ]
    for name in judge_pools:
        splits = JUDGE_POOLS[name]
        rows = [
            *load(stage_a, tasks=selected, splits=splits, judge=True, phase=PHASE, root=root),
            *load(stage_b, tasks=selected, splits=splits, judge=True, phase=PHASE, root=root),
        ]
        pool = f"Stage A+B, selected tasks, {name}"
        gate = not_done_tasks(rows)
        lines += [
            f"## {pool}: in-loop judge against primary truth",
            "",
            f"Tasks: {', '.join(sorted({r.task_id for r in rows}))}. {len(rows)} boundaries. "
            f"Distinct tasks with a primary not-done boundary: {gate}.",
            "",
        ]
        if gate < MIN_NOT_DONE_TASKS:
            lines += [
                f"Fewer than {MIN_NOT_DONE_TASKS}: the pool fails the reporting rule. Per-task "
                "counts only, with no judge rate, point estimate or interval, per task or pooled.",
                "",
            ]
        else:
            for f in judge_figures(pool, rows, seed=seed, root=root):
                lines += render(f)
        lines += [
            "Judge-vs-truth contingency counts. Judge decisions: wait counted as continue; "
            "none means the in-loop judge never answered.",
            "",
            *render_contingency(contingency(rows, root)),
        ]
    return "\n".join(lines).rstrip("\n") + "\n"


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()
