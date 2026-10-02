"""Phase 2 analysis: per arm and cell, reliability first, then error rates, then hypotheses.

Rules (prereg "Analysis rules" and the amendment "Phase 2 design"):

* Truth is the adjudicated human label (primary) or the verifier (sensitivity). Boundaries
  labelled ``ambiguous`` leave the primary analysis and are listed.
* Each boundary is judged 3 times. Its item decision is the decision at least 2 of 3 samples
  share, and ``tie`` when all three differ; a tie is not DONE, and it is never correct. Decisions
  are production (effective) decisions: parse failures and format violations count as the
  CONTINUE Hermes falls back to. The first sample alone is reported as a sensitivity check.
* False-DONE and false-CONTINUE get Wilson intervals (items as independent) and task-clustered
  bootstrap intervals (2,000 resamples). Cells under 20 items show counts only.
* Paired comparisons use exact McNemar on the item decisions. H4's four tests are the planned,
  Holm-corrected family; everything else is exploratory. Fewer than 15 discordant pairs, or an
  interval that includes 0, reads "no detectable difference at n = ...".
* Agent arms are never pooled, and records from different judge arms never share a cell.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from hjr import metrics, stats
from hjr.phase2 import Plan, resolve
from hjr.schemas import AttemptRecord, BoundaryRecord, JudgeVerdict, LabelRecord

DECISIONS = ("done", "continue", "blocked")
EXPECTED = metrics.EXPECTED_DECISION
H4_DELTA_FD = 0.10  # false-DONE must fall by at least 10 points
H4_MAX_FC_RISE = 0.05  # false-CONTINUE may rise by at most 5 points


# ── Truth ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Truth:
    source: str  # "labels" | "verifier"
    states: dict[str, str]  # boundary id -> done | not_done | blocked
    ambiguous: list[str] = field(default_factory=list)
    unlabelled: list[str] = field(default_factory=list)


def truth_from_verifier(boundaries: Iterable[BoundaryRecord]) -> Truth:
    return Truth("verifier", metrics.truth_map(boundaries))


def truth_from_labels(labels: Iterable[LabelRecord], boundaries: Iterable[BoundaryRecord]) -> Truth:
    """The latest adjudicated label per boundary. Ambiguous and unlabelled ones are listed."""
    latest: dict[str, LabelRecord] = {}
    for rec in labels:
        if rec.stage == "adjudicated":
            prev = latest.get(rec.boundary_id)
            if prev is None or rec.ts >= prev.ts:
                latest[rec.boundary_id] = rec
    states, ambiguous, unlabelled = {}, [], []
    for b in boundaries:
        rec = latest.get(b.boundary_id)
        if rec is None:
            unlabelled.append(b.boundary_id)
        elif rec.label == "ambiguous":
            ambiguous.append(b.boundary_id)
        else:
            states[b.boundary_id] = rec.label
    return Truth("labels", states, sorted(ambiguous), sorted(unlabelled))


# ── Items ─────────────────────────────────────────────────────────────


def item_decision(decisions: Sequence[str]) -> str:
    """The decision at least 2 of 3 samples share; 'tie' when none does."""
    if not decisions:
        return "tie"
    top, n = Counter(decisions).most_common(1)[0]
    return top if n * 2 > len(decisions) else "tie"


@dataclass(frozen=True)
class Item:
    boundary_id: str
    task_id: str
    category: str
    split: str
    truth: str
    decisions: tuple[str, ...]  # effective decision per sample, in sample order

    @property
    def decision(self) -> str:
        return item_decision(self.decisions)

    @property
    def first(self) -> str:
        return self.decisions[0]

    def judged_done(self, first_only: bool = False) -> bool:
        return (self.first if first_only else self.decision) == "done"

    @property
    def correct(self) -> bool:
        return self.decision == EXPECTED[self.truth]

    @property
    def unanimous(self) -> bool:
        return len(set(self.decisions)) == 1


def build_items(
    verdicts: Sequence[JudgeVerdict],
    boundaries: Mapping[str, BoundaryRecord],
    truth: Truth,
    *,
    samples: int,
) -> tuple[list[Item], list[str]]:
    """Items with every sample present. Returns (items, ids missing at least one sample)."""
    by_item: dict[str, dict[int, str]] = defaultdict(dict)
    for v in verdicts:
        by_item[v.boundary_id][v.sample] = v.decision
    items, incomplete = [], []
    for bid, b in boundaries.items():
        if bid not in truth.states:
            continue
        got = by_item.get(bid, {})
        if len(got) < samples or any(s not in got for s in range(samples)):
            incomplete.append(bid)
            continue
        decisions = tuple(got[s] for s in range(samples))
        items.append(Item(bid, b.task_id, b.category, b.split, truth.states[bid], decisions))
    return items, sorted(incomplete)


# ── Rates ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RateCI:
    k: int
    n: int
    wilson: tuple[float, float] | None
    boot: stats.BootstrapCI

    def render(self) -> str:
        if self.n == 0:
            return "–"
        if self.n < stats.MIN_ITEMS_FOR_PERCENT:
            return f"{self.k}/{self.n}"
        b = self.boot
        boot = f"; task-bootstrap {_pct(b.low)}–{_pct(b.high)}" if b.low is not None else ""
        w = self.wilson
        return (
            f"{self.k}/{self.n} ({_pct(self.k / self.n)}; Wilson {_pct(w[0])}–{_pct(w[1])}{boot})"
        )


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{100 * x:.1f}%"


def _rate(items: Sequence[Item], hit, *, seed: str) -> RateCI:
    k = sum(hit(i) for i in items)
    n = len(items)

    def statistic(rows: Sequence[Item]) -> float | None:
        return sum(hit(i) for i in rows) / len(rows) if rows else None

    boot = stats.cluster_bootstrap(items, lambda i: i.task_id, statistic, seed=seed)
    return RateCI(k, n, stats.wilson(k, n), boot)


def false_done(items: Sequence[Item], *, seed: str, first_only: bool = False) -> RateCI:
    neg = [i for i in items if i.truth != "done"]
    return _rate(neg, lambda i: i.judged_done(first_only), seed=seed)


def false_continue(items: Sequence[Item], *, seed: str, first_only: bool = False) -> RateCI:
    pos = [i for i in items if i.truth == "done"]
    return _rate(pos, lambda i: not i.judged_done(first_only), seed=seed)


def fd_minus_fc(items: Sequence[Item], *, seed: str) -> stats.BootstrapCI:
    """H1: false-DONE rate minus false-CONTINUE rate, task-clustered bootstrap."""

    def statistic(rows: Sequence[Item]) -> float | None:
        neg = [i for i in rows if i.truth != "done"]
        pos = [i for i in rows if i.truth == "done"]
        if not neg or not pos:
            return None
        return sum(i.judged_done() for i in neg) / len(neg) - sum(
            not i.judged_done() for i in pos
        ) / len(pos)

    return stats.cluster_bootstrap(items, lambda i: i.task_id, statistic, seed=seed)


# ── Paired comparisons ───────────────────────────────────────────────


@dataclass(frozen=True)
class Paired:
    name: str
    baseline: str
    candidate: str
    n: int
    test: stats.McNemar
    # candidate minus baseline, task-clustered bootstrap
    delta: stats.BootstrapCI
    p_holm: float | None = None

    def verdict(self) -> str:
        d = self.delta
        if not self.test.detectable or d.low is None or d.low <= 0 <= d.high:
            return f"no detectable difference at n = {self.n}"
        return "difference detected"


def paired(
    name: str,
    baseline: tuple[str, Sequence[Item]],
    candidate: tuple[str, Sequence[Item]],
    indicator,
    *,
    seed: str,
    restrict=lambda i: True,
) -> Paired:
    """McNemar on ``indicator`` over items present in both cells (and passing ``restrict``)."""
    b = {i.boundary_id: i for i in baseline[1] if restrict(i)}
    c = {i.boundary_id: i for i in candidate[1] if restrict(i)}
    shared = sorted(b.keys() & c.keys())
    pairs = [(b[k], c[k]) for k in shared]
    test = stats.mcnemar_exact([indicator(x) for x, _ in pairs], [indicator(y) for _, y in pairs])

    def statistic(rows):
        if not rows:
            return None
        return sum(indicator(y) - indicator(x) for x, y in rows) / len(rows)

    delta = stats.cluster_bootstrap(pairs, lambda p: p[0].task_id, statistic, seed=seed)
    return Paired(name, baseline[0], candidate[0], len(shared), test, delta)


# ── Per-cell reports ──────────────────────────────────────────────────


@dataclass(frozen=True)
class CellReport:
    arm: str
    cell: str
    variant: str
    scores: metrics.JudgeScores | None
    transport: metrics.TransportStats
    items: list[Item]
    incomplete: list[str]
    false_done: RateCI
    false_continue: RateCI
    false_done_first: RateCI
    false_continue_first: RateCI
    unanimous: tuple[int, int]
    # Codex arm only: replies that did not match the verdict schema exactly
    schema_invalid: tuple[int, int] | None
    kappa: stats.Agreement


def cell_report(
    arm: str,
    cell: str,
    variant: str,
    verdicts: Sequence[JudgeVerdict],
    attempts: Sequence[AttemptRecord],
    boundaries: Mapping[str, BoundaryRecord],
    truth: Truth,
    *,
    samples: int,
    seed: str,
) -> CellReport:
    scored = [v for v in verdicts if v.boundary_id in truth.states]
    scores = metrics.score(scored, truth.states, what=f"{arm} {cell}") if scored else None
    items, incomplete = build_items(verdicts, boundaries, truth, samples=samples)
    key = f"{seed}:{arm}:{cell}"
    meta = [v.harness_meta for v in verdicts if v.harness_meta and "schema_valid" in v.harness_meta]
    invalid = (sum(m["schema_valid"] != "true" for m in meta), len(meta)) if meta else None
    pairs = [
        ("done" if i.truth == "done" else "not_done", "done" if i.judged_done() else "not_done")
        for i in items
    ]
    return CellReport(
        arm=arm,
        cell=cell,
        variant=variant,
        scores=scores,
        transport=metrics.transport_stats(attempts, verdicts, variant=variant),
        items=items,
        incomplete=incomplete,
        false_done=false_done(items, seed=f"{key}:fd"),
        false_continue=false_continue(items, seed=f"{key}:fc"),
        false_done_first=false_done(items, seed=f"{key}:fd1", first_only=True),
        false_continue_first=false_continue(items, seed=f"{key}:fc1", first_only=True),
        unanimous=(sum(i.unanimous for i in items), len(items)),
        schema_invalid=invalid,
        kappa=stats.agreement(pairs, ["done", "not_done"]),
    )


# ── Whole report ──────────────────────────────────────────────────────


@dataclass
class Report:
    truth_source: str
    plan: Plan
    cells: dict[tuple[str, str], CellReport] = field(default_factory=dict)
    truth: dict[str, Truth] = field(default_factory=dict)
    h1: dict[str, stats.BootstrapCI] = field(default_factory=dict)
    h4: list[Paired] = field(default_factory=list)
    h4_guard: list[Paired] = field(default_factory=list)
    exploratory: list[Paired] = field(default_factory=list)
    sanity: dict[tuple[str, str], tuple[int, int]] = field(default_factory=dict)


SELF_CELL = "prod-plain:self:head4k"
SPLITS = ("heldout", "dev")
# H4: production prompt and view against repair-v1 with evidence, per judge model.
H4_PAIRS = (
    ("prod-plain:flash:head4k", "repair-v1:flash:evidence"),
    ("prod-plain:strong:head4k", "repair-v1:strong:evidence"),
)
# H5 (exploratory): judge models against each other on the production prompt and view.
H5_PAIRS = (
    (SELF_CELL, "prod-plain:flash:head4k"),
    (SELF_CELL, "prod-plain:strong:head4k"),
    ("prod-plain:flash:head4k", "prod-plain:strong:head4k"),
)
# Separates the evidence view from the repair prompt (exploratory).
DECOMPOSITION = (
    ("prod-plain:flash:head4k", "prod-plain:flash:evidence"),
    ("prod-plain:flash:evidence", "repair-v1:flash:evidence"),
)


def _is_fd(i: Item) -> bool:
    return i.judged_done()


def _is_fc(i: Item) -> bool:
    return not i.judged_done()


def _correct(i: Item) -> bool:
    return i.correct


def _sanity(
    plan: Plan,
    arm: str,
    report: Report,
    by_id: Mapping[str, BoundaryRecord],
    rows: Sequence[JudgeVerdict],
) -> None:
    """Item-decision agreement between the Codex arm and the paid API on the sanity subset."""
    ids = plan.sanity_ids(arm)
    verifier = truth_from_verifier(by_id[k] for k in ids)
    for api_variant in plan.sanity["variants"]:
        cli_cell = api_variant.replace(":strong-api:", ":strong:")
        cli = {i.boundary_id: i for i in report.cells[(arm, cli_cell)].items}
        api, _ = build_items(
            [v for v in rows if v.variant == api_variant],
            {k: by_id[k] for k in ids},
            verifier,
            samples=int(plan.sanity["samples"]),
        )
        both = [(cli[i.boundary_id], i) for i in api if i.boundary_id in cli]
        report.sanity[(arm, cli_cell)] = (sum(x.decision == y.decision for x, y in both), len(both))


def analyse(
    plan: Plan,
    truth: Mapping[str, Truth],
    boundaries: Mapping[str, Sequence[BoundaryRecord]],
    verdicts: Mapping[str, Sequence[JudgeVerdict]],
    attempts: Mapping[str, Sequence[AttemptRecord]],
    sanity: Mapping[str, Sequence[JudgeVerdict]] | None = None,
) -> Report:
    seed = plan.seed("bootstrap")
    sources = {t.source for t in truth.values()}
    if len(sources) != 1:
        raise ValueError(f"one truth source per report, got {sorted(sources)}")
    report = Report(truth_source=sources.pop(), plan=plan, truth=dict(truth))
    for arm in plan.arms:
        by_id = {b.boundary_id: b for b in boundaries[arm]}
        rows = [v for v in verdicts.get(arm, []) if v.boundary_id in by_id]
        planned = {str(resolve(cell, arm)) for cell in plan.cells}
        stray = sorted({v.variant for v in rows} - planned)
        if stray:
            raise ValueError(f"{arm} run holds variants outside the plan: {stray}")
        for cell in plan.cells:
            variant = str(resolve(cell, arm))
            report.cells[(arm, cell)] = cell_report(
                arm,
                cell,
                variant,
                [v for v in rows if v.variant == variant],
                attempts.get(arm, []),
                by_id,
                truth[arm],
                samples=plan.samples,
                seed=seed,
            )
        report.h1[arm] = fd_minus_fc(report.cells[(arm, SELF_CELL)].items, seed=f"{seed}:{arm}:h1")

        def cell(name: str, _arm: str = arm) -> tuple[str, list[Item]]:
            return name, report.cells[(_arm, name)].items

        for base, cand in H4_PAIRS:
            for split in SPLITS:
                fd = paired(
                    f"{arm} · {split} · false-DONE",
                    cell(base),
                    cell(cand),
                    _is_fd,
                    seed=f"{seed}:{arm}:{base}:{cand}:{split}:fd",
                    restrict=lambda i, s=split: i.split == s and i.truth != "done",
                )
                fc = paired(
                    f"{arm} · {split} · false-CONTINUE",
                    cell(base),
                    cell(cand),
                    _is_fc,
                    seed=f"{seed}:{arm}:{base}:{cand}:{split}:fc",
                    restrict=lambda i, s=split: i.split == s and i.truth == "done",
                )
                if split == "heldout":
                    report.h4.append(fd)
                    report.h4_guard.append(fc)
                else:
                    report.exploratory += [fd, fc]
        for base, cand in DECOMPOSITION:
            report.exploratory.append(
                paired(
                    f"{arm} · all · false-DONE",
                    cell(base),
                    cell(cand),
                    _is_fd,
                    seed=f"{seed}:{arm}:{base}:{cand}:dec",
                    restrict=lambda i: i.truth != "done",
                )
            )
        for base, cand in H5_PAIRS:
            report.exploratory.append(
                paired(
                    f"{arm} · all · correct",
                    cell(base),
                    cell(cand),
                    _correct,
                    seed=f"{seed}:{arm}:{base}:{cand}:h5",
                )
            )
        if sanity and sanity.get(arm):
            _sanity(plan, arm, report, by_id, sanity[arm])
    adjusted = stats.holm({f"{p.name} {p.candidate}": p.test.p for p in report.h4})
    report.h4 = [
        Paired(
            p.name,
            p.baseline,
            p.candidate,
            p.n,
            p.test,
            p.delta,
            adjusted[f"{p.name} {p.candidate}"],
        )
        for p in report.h4
    ]
    return report


def h4_met(fd: Paired, fc: Paired) -> bool:
    """H4's acceptance rule: a detectable fall in false-DONE of at least 10 points, and a
    false-CONTINUE rise of at most 5 points (upper bound of its interval)."""
    d, g = fd.delta, fc.delta
    if fd.verdict() != "difference detected" or d.high is None or g.high is None:
        return False
    return d.high <= -H4_DELTA_FD and g.high <= H4_MAX_FC_RISE


# ── Rendering ─────────────────────────────────────────────────────────


def _p(x: float | None) -> str:
    return "–" if x is None else f"{x:.3g}"


def _delta(d: stats.BootstrapCI) -> str:
    if d.estimate is None:
        return "–"
    ci = f" ({_pct(d.low)} to {_pct(d.high)})" if d.low is not None else ""
    return f"{100 * d.estimate:+.1f} pp{ci}"


def _paired_table(rows: Sequence[Paired], holm: bool) -> list[str]:
    cols = ["Comparison", "Baseline → candidate", "n", "Discordant (b/c)", "Δ", "p"]
    if holm:
        cols.append("Holm p")
    cols.append("Reading")
    out = ["| " + " | ".join(cols) + " |", "|---" * len(cols) + "|"]
    for p in rows:
        cells = [
            p.name,
            f"`{p.baseline}` → `{p.candidate}`",
            str(p.n),
            f"{p.test.discordant} ({p.test.b}/{p.test.c})",
            _delta(p.delta),
            _p(p.test.p),
        ]
        if holm:
            cells.append(_p(p.p_holm))
        cells.append(p.verdict())
        out.append("| " + " | ".join(cells) + " |")
    return out


def _kappa(k: stats.Agreement) -> str:
    if k.kappa is None:
        return "–"
    return f"{k.kappa:.2f} (PABAK {k.pabak:.2f}; done prevalence {k.prevalence['done']:.2f})"


def _arm_section(report: Report, arm: str) -> list[str]:
    plan = report.plan
    lines = ["", f"## Arm: {arm}", "", "### Reliability", ""]
    lines += [
        "| Cell | Model calls | Transport errors / attempts | Unresolved | Parse failed "
        "| Format violations | Schema-invalid (CLI) |",
        "|---|---|---|---|---|---|---|",
    ]
    for name in plan.cells:
        c = report.cells[(arm, name)]
        s = c.scores
        inv = "n/a" if c.schema_invalid is None else stats.fmt_count(*c.schema_invalid)
        lines.append(
            f"| `{c.variant}` | {s.model_calls if s else 0} | "
            f"{c.transport.errors}/{c.transport.attempts} | {c.transport.unresolved_calls} | "
            f"{s.parse_failures if s else '–'} | {s.format_violations if s else '–'} | {inv} |"
        )
    lines += ["", "### Accuracy (calls) and error rates (items)", ""]
    lines += [
        "| Cell | Semantic acc. | Effective acc. | Strict acc. | False-DONE | False-CONTINUE "
        "| False-DONE, 1st sample | False-CONTINUE, 1st sample | Unanimous items | κ |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name in plan.cells:
        c = report.cells[(arm, name)]
        s = c.scores
        lines.append(
            f"| `{c.variant}` | {s.semantic_accuracy if s else '–'} | "
            f"{s.effective_accuracy if s else '–'} | {s.strict_accuracy if s else '–'} | "
            f"{c.false_done.render()} | {c.false_continue.render()} | "
            f"{c.false_done_first.render()} | {c.false_continue_first.render()} | "
            f"{stats.fmt_count(*c.unanimous)} | {_kappa(c.kappa)} |"
        )
    missing = {n: report.cells[(arm, n)].incomplete for n in plan.cells}
    for name, ids in missing.items():
        if ids:
            lines.append(f"\n`{name}`: {len(ids)} boundaries lack a sample and are left out.")
    self_cell = report.cells[(arm, SELF_CELL)]
    lines += [
        "",
        "### H1: false-DONE against false-CONTINUE under the production self judge",
        "",
        f"False-DONE {self_cell.false_done.render()}; false-CONTINUE "
        f"{self_cell.false_continue.render()}; FD − FC {_delta(report.h1[arm])}. "
        "H1 predicts a negative difference.",
        "",
        "### H2: false-DONE by category (counts, truth ≠ done)",
        "",
    ]
    cats = sorted({i.category for c in plan.cells for i in report.cells[(arm, c)].items})
    lines += ["| Cell | " + " | ".join(cats) + " |", "|---" * (len(cats) + 1) + "|"]
    for name in plan.cells:
        items = report.cells[(arm, name)].items
        row = []
        for cat in cats:
            neg = [i for i in items if i.category == cat and i.truth != "done"]
            row.append(stats.fmt_count(sum(i.judged_done() for i in neg), len(neg)))
        lines.append(f"| `{name}` | " + " | ".join(row) + " |")
    return lines


def render(report: Report) -> str:
    lines = [
        f"# Phase 2 summary (truth: {report.truth_source})",
        "",
        "Generated by `hjr phase2-summary`. Agent arms are reported separately and never pooled. "
        "Item decision: the decision at least 2 of 3 samples share; a three-way split is a tie, "
        "which is not DONE and never correct. Cells under 20 items show counts only. Δ is "
        "candidate minus baseline, with a task-clustered bootstrap interval.",
        "",
    ]
    for arm, t in report.truth.items():
        lines.append(
            f"- {arm}: {len(t.states)} boundaries with truth; {len(t.ambiguous)} ambiguous "
            f"(excluded); {len(t.unlabelled)} unlabelled."
        )
    for arm in report.plan.arms:
        lines += _arm_section(report, arm)
    lines += [
        "",
        "## H4 (planned, Holm-corrected): repair-v1 on held-out boundaries",
        "",
        f"Met when false-DONE falls by at least {100 * H4_DELTA_FD:.0f} points (interval "
        f"excluding 0, 15+ discordant pairs) and false-CONTINUE rises by at most "
        f"{100 * H4_MAX_FC_RISE:.0f} points.",
        "",
    ]
    lines += _paired_table(report.h4, holm=True)
    lines += ["", "False-CONTINUE on held-out done items:", ""]
    lines += _paired_table(report.h4_guard, holm=False)
    lines += [""]
    for fd, fc in zip(report.h4, report.h4_guard, strict=True):
        lines.append(f"- {fd.name}, `{fd.candidate}`: H4 {'met' if h4_met(fd, fc) else 'not met'}.")
    lines += ["", "## Exploratory comparisons (unadjusted)", ""]
    lines += _paired_table(report.exploratory, holm=False)
    if report.sanity:
        lines += [
            "",
            "## Strong-judge harness sanity check",
            "",
            "GPT-6.1 Sol via Codex CLI (harness prompt and sampling params not controllable) "
            "against the same model through the paid API, with the same prompts, on the "
            "preregistered subset. Item decisions that agree:",
            "",
            "| Arm | Cell | Agreeing items |",
            "|---|---|---|",
        ]
        for (arm, name), (k, n) in sorted(report.sanity.items()):
            lines.append(f"| {arm} | `{name}` | {k}/{n} |")
    for arm, t in report.truth.items():
        if t.ambiguous:
            lines += ["", f"Ambiguous ({arm}): " + ", ".join(f"`{b}`" for b in t.ambiguous)]
    return "\n".join(lines) + "\n"
