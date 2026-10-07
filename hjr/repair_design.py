"""repair-v1 design iterations (prereg Amendment 3): the dev design set and the iteration report.

Each iteration replays ``repair-v1:flash:evidence`` over every source below, dev rows only, into
``results/runs/repair-i<n>-<source>``. The report reads those runs; it makes no model calls.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from hjr.analysis import item_decision
from hjr.config import ROOT
from hjr.regrade import primary_rows, primary_verifier
from hjr.replay import load_verdicts
from hjr.schemas import BoundaryRecord, RunManifest, read_jsonl

RUNS = ROOT / "results" / "runs"
FROZEN = ROOT / "data" / "frozen"
REPORTS = ROOT / "results" / "repair"
VARIANT = "repair-v1:flash:evidence"
SAMPLES = 3
MAX_ITERATIONS = 3
MAX_FALSE_CONTINUE = 0.05
PILOT = "pilot"

# Source name -> frozen boundaries file. Pilot truth is fixed by construction; the rest is
# primary truth from `hjr regrade`.
SOURCES = {
    PILOT: FROZEN / "pilot_boundaries.jsonl",
    "p1a-weak": FROZEN / "phase1-weak.jsonl",
    "p1a-strong": FROZEN / "phase1-strong.jsonl",
    "p1b-a": FROZEN / "phase1b-weak-a.jsonl",
    "p1b-b": FROZEN / "phase1b-weak-b.jsonl",
}


def run_id(iteration: int, source: str) -> str:
    if not 1 <= iteration <= MAX_ITERATIONS:
        raise ValueError(f"repair-v1 design allows iterations 1 to {MAX_ITERATIONS}")
    return f"repair-i{iteration}-{source}"


def design_boundaries(source: str) -> list[BoundaryRecord]:
    return [b for b in read_jsonl(SOURCES[source], BoundaryRecord) if b.split == "dev"]


def truth_states(source: str, boundaries: Sequence[BoundaryRecord]) -> dict[str, str]:
    if source == PILOT:
        return {b.boundary_id: b.verifier.truth_state for b in boundaries}
    rows = primary_rows(SOURCES[source])
    return {b.boundary_id: primary_verifier(rows[b.boundary_id]).truth_state for b in boundaries}


@dataclass(frozen=True)
class DesignItem:
    source: str
    boundary_id: str
    group: str  # task id, or the pilot item's category
    truth: str
    decisions: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def decision(self) -> str:
        return item_decision(self.decisions)

    @property
    def natural(self) -> bool:
        return self.source != PILOT

    @property
    def false_done(self) -> bool:
        return self.truth != "done" and self.decision == "done"

    @property
    def false_continue(self) -> bool:
        return self.truth == "done" and self.decision != "done"


@dataclass
class SourceRun:
    source: str
    items: list[DesignItem]
    incomplete: list[str]
    calls: int
    outcomes: Counter
    cost_usd: float
    git_sha: str | None
    git_dirty: bool | None


def load_run(iteration: int, source: str, runs: Path = RUNS) -> SourceRun:
    boundaries = design_boundaries(source)
    truth = truth_states(source, boundaries)
    run_dir = runs / run_id(iteration, source)
    verdicts = (
        [v for v in load_verdicts(run_dir) if v.variant == VARIANT] if run_dir.exists() else []
    )
    by_item: dict[str, dict[int, tuple[str, str]]] = defaultdict(dict)
    for v in verdicts:
        by_item[v.boundary_id][v.sample] = (v.decision, v.reason)
    items, incomplete = [], []
    for b in boundaries:
        got = by_item.get(b.boundary_id, {})
        if any(s not in got for s in range(SAMPLES)):
            incomplete.append(b.boundary_id)
            continue
        samples = [got[s] for s in range(SAMPLES)]
        group = b.category if source == PILOT else b.task_id.removeprefix("hjr/")
        items.append(
            DesignItem(
                source,
                b.boundary_id,
                group,
                truth[b.boundary_id],
                tuple(d for d, _ in samples),
                tuple(r for _, r in samples),
            )
        )
    sha = dirty = None
    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        m = RunManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        sha, dirty = m.git_sha, m.git_dirty
    return SourceRun(
        source,
        items,
        incomplete,
        calls=sum(v.outcome != "no_call" for v in verdicts),
        outcomes=Counter(v.outcome for v in verdicts),
        cost_usd=sum(v.cost_usd or 0.0 for v in verdicts),
        git_sha=sha,
        git_dirty=dirty,
    )


@dataclass(frozen=True)
class Score:
    """The figures the selection rule of Amendment 3 reads."""

    natural_false_done: int
    natural_not_done: int  # natural not-done and blocked items
    natural_false_continue: int
    natural_done: int
    pilot_false_done: int
    pilot_not_done: int
    pilot_false_continue: int
    pilot_done: int

    @property
    def false_continue_rate(self) -> float:
        return self.natural_false_continue / self.natural_done if self.natural_done else 0.0

    @property
    def eligible(self) -> bool:
        return self.false_continue_rate <= MAX_FALSE_CONTINUE


def score(items: Sequence[DesignItem]) -> Score:
    nat = [i for i in items if i.natural]
    pil = [i for i in items if not i.natural]
    return Score(
        natural_false_done=sum(i.false_done for i in nat),
        natural_not_done=sum(i.truth != "done" for i in nat),
        natural_false_continue=sum(i.false_continue for i in nat),
        natural_done=sum(i.truth == "done" for i in nat),
        pilot_false_done=sum(i.false_done for i in pil),
        pilot_not_done=sum(i.truth != "done" for i in pil),
        pilot_false_continue=sum(i.false_continue for i in pil),
        pilot_done=sum(i.truth == "done" for i in pil),
    )


def select(scores: dict[int, Score]) -> int:
    """Amendment 3: fewest natural false-DONE among iterations within the false-CONTINUE bound,
    then fewer pilot false-DONE, then the later iteration; with none within the bound, the
    lowest natural false-CONTINUE (then the later iteration)."""
    eligible = {n: s for n, s in scores.items() if s.eligible}
    if eligible:
        return min(
            eligible,
            key=lambda n: (eligible[n].natural_false_done, eligible[n].pilot_false_done, -n),
        )
    return min(scores, key=lambda n: (scores[n].false_continue_rate, -n))


# ── Report ────────────────────────────────────────────────────────────


def _frac(k: int, n: int) -> str:
    return f"{k}/{n}" + (f" ({k / n:.1%})" if n else "")


def report(iteration: int, runs: Path = RUNS) -> str:
    sources = [load_run(iteration, s, runs) for s in SOURCES]
    items = [i for r in sources for i in r.items]
    shas = {r.git_sha for r in sources}
    lines = [
        f"# repair-v1 design iteration {iteration}",
        "",
        f"`{VARIANT}`, {SAMPLES} samples, dev design set of prereg Amendment 3. Item decision: "
        "the effective decision at least 2 of 3 samples share; a tie is not DONE. "
        "Design-set figures are descriptive, never evaluation.",
        "",
        f"Commit: {', '.join(f'`{s}`' for s in sorted(map(str, shas)))}"
        + ("; **dirty tree**" if any(r.git_dirty for r in sources) else ""),
        f"Spend: ${sum(r.cost_usd for r in sources):.4f} "
        f"over {sum(r.calls for r in sources)} calls.",
        "",
        "## Reliability",
        "",
        "| Source | Items | Incomplete | Calls | Parsed | Parse failed | Format violation "
        "| No call |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in sources:
        o = r.outcomes
        lines.append(
            f"| {r.source} | {len(r.items)} | {len(r.incomplete)} | {r.calls} | {o['parsed']} | "
            f"{o['parse_failed']} | {o['format_violation']} | {o['no_call']} |"
        )
    s = score(items)
    figures = [
        (
            "Natural false-DONE (truth not done or blocked)",
            s.natural_false_done,
            s.natural_not_done,
        ),
        ("Natural false-CONTINUE (truth done)", s.natural_false_continue, s.natural_done),
        ("Pilot false-DONE", s.pilot_false_done, s.pilot_not_done),
        ("Pilot false-CONTINUE", s.pilot_false_continue, s.pilot_done),
    ]
    lines += ["", "## Selection figures", "", "| Figure | Items |", "|---|---|"]
    lines += [f"| {name} | {_frac(k, n)} |" for name, k, n in figures]
    bound = f"Within the {MAX_FALSE_CONTINUE:.0%} false-CONTINUE bound"
    lines += [
        f"| {bound} | {'yes' if s.eligible else 'no'} |",
        "",
        "## Item decisions by source and truth",
        "",
        "| Source | Truth | Items | done | continue | blocked | wait | tie |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in sources:
        for truth in ("done", "not_done", "blocked"):
            rows = [i for i in r.items if i.truth == truth]
            if not rows:
                continue
            c = Counter(i.decision for i in rows)
            lines.append(
                f"| {r.source} | {truth} | {len(rows)} | {c['done']} | {c['continue']} | "
                f"{c['blocked']} | {c['wait']} | {c['tie']} |"
            )
    lines += [
        "",
        "## By task or pilot group",
        "",
        "| Group | Truth | Items | Judged done |",
        "|---|---|---|---|",
    ]
    groups: dict[tuple[str, str], list[DesignItem]] = defaultdict(list)
    for i in items:
        groups[(i.group, i.truth)].append(i)
    for (group, truth), rows in sorted(groups.items()):
        lines.append(
            f"| {group} | {truth} | {len(rows)} | {sum(i.decision == 'done' for i in rows)} |"
        )
    errors = [i for i in items if i.false_done or i.false_continue]
    lines += ["", "## Errors", ""]
    if not errors:
        lines.append("None.")
    else:
        lines += ["| Boundary | Truth | Decisions | First reason |", "|---|---|---|---|"]
        for i in sorted(errors, key=lambda i: (i.truth, i.boundary_id)):
            reason = i.reasons[0].replace("|", "\\|").replace("\n", " ")
            lines.append(f"| `{i.boundary_id}` | {i.truth} | {'/'.join(i.decisions)} | {reason} |")
    return "\n".join(lines) + "\n"


def scores(runs: Path = RUNS) -> dict[int, Score]:
    """Scores of every complete iteration on disk."""
    out = {}
    for n in range(1, MAX_ITERATIONS + 1):
        loaded = [load_run(n, s, runs) for s in SOURCES]
        if all(r.items and not r.incomplete for r in loaded):
            out[n] = score([i for r in loaded for i in r.items])
    return out
