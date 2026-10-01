"""Judge-model drift: the same frozen items, prompt and view under two judge arms.

Two questions, kept apart:

* Do the verdicts change? Disagreement and DONE<->CONTINUE flips, call by call (paired on
  boundary and sample index) and item by item (majority decision), stratified by category and
  scenario. Truth plays no part here.
* Does correctness change? Per-item majority correctness against truth, compared with an exact
  McNemar test. The same paired records go to NeMo Evaluator's ``compare_results`` when the
  ``nel`` extra is installed.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from scipy.stats import binomtest

from hjr import metrics
from hjr.judge import Variant
from hjr.schemas import BoundaryRecord, JudgeVerdict

DECISIONS = ("done", "continue", "blocked")


def _majority(decisions: list[str]) -> str:
    counts = Counter(decisions)
    top = max(counts.values())
    leaders = [d for d in DECISIONS if counts.get(d) == top]
    return leaders[0] if len(leaders) == 1 else "tie"


@dataclass
class Stratum:
    calls: int = 0
    call_disagreements: int = 0
    items: int = 0
    item_disagreements: int = 0


@dataclass
class DriftReport:
    baseline: str
    candidate: str
    paired_items: int
    paired_calls: int
    unpaired_items: dict[str, int]
    call_transitions: Counter = field(default_factory=Counter)
    item_transitions: Counter = field(default_factory=Counter)
    strata: dict[str, Stratum] = field(default_factory=dict)
    flipped_items: list[dict] = field(default_factory=list)
    # Correctness against truth (item majority): baseline-only correct, candidate-only correct
    correct_both: int = 0
    correct_baseline_only: int = 0
    correct_candidate_only: int = 0
    correct_neither: int = 0
    mcnemar_p: float | None = None
    nel_report: dict | None = None

    @property
    def call_disagreement(self) -> metrics.Rate:
        changed = sum(n for (a, b), n in self.call_transitions.items() if a != b)
        return metrics.Rate(changed, self.paired_calls)

    @property
    def item_disagreement(self) -> metrics.Rate:
        changed = sum(n for (a, b), n in self.item_transitions.items() if a != b)
        return metrics.Rate(changed, self.paired_items)


def _check_variants(baseline: list[JudgeVerdict], candidate: list[JudgeVerdict]) -> None:
    metrics.check_poolable(baseline, what="baseline")
    metrics.check_poolable(candidate, what="candidate")
    b, c = Variant.parse(baseline[0].variant), Variant.parse(candidate[0].variant)
    if (b.prompt, b.view) != (c.prompt, c.view):
        raise ValueError(f"drift needs the same prompt and view: {b} vs {c}")
    if baseline[0].arm_id == candidate[0].arm_id:
        raise ValueError("baseline and candidate are the same arm")


def compare(
    boundaries: Iterable[BoundaryRecord],
    baseline: list[JudgeVerdict],
    candidate: list[JudgeVerdict],
) -> DriftReport:
    _check_variants(baseline, candidate)
    boundaries = list(boundaries)
    truth = metrics.truth_map(boundaries)
    meta = {b.boundary_id: b for b in boundaries}

    def by_item(rows: list[JudgeVerdict]) -> dict[str, dict[int, str]]:
        out: dict[str, dict[int, str]] = defaultdict(dict)
        for v in rows:
            out[v.boundary_id][v.sample] = v.decision
        return out

    base, cand = by_item(baseline), by_item(candidate)
    shared = sorted(set(base) & set(cand) & set(truth))
    report = DriftReport(
        baseline=baseline[0].variant,
        candidate=candidate[0].variant,
        paired_items=len(shared),
        paired_calls=0,
        unpaired_items={
            "baseline_only": len(set(base) - set(cand)),
            "candidate_only": len(set(cand) - set(base)),
        },
    )
    strata: dict[str, Stratum] = defaultdict(Stratum)
    expected = metrics.EXPECTED_DECISION
    nel_base, nel_cand = {}, {}

    for idx, bid in enumerate(shared):
        b_item, c_item = base[bid], cand[bid]
        keys = [f"category={meta[bid].category}"]
        if "scenario" in meta[bid].tags:
            keys.append(f"scenario={meta[bid].tags['scenario']}")
        call_changes = 0
        for s in sorted(set(b_item) & set(c_item)):
            pair = (b_item[s], c_item[s])
            report.call_transitions[pair] += 1
            report.paired_calls += 1
            call_changes += pair[0] != pair[1]
        b_maj = _majority(list(b_item.values()))
        c_maj = _majority(list(c_item.values()))
        report.item_transitions[(b_maj, c_maj)] += 1
        for key in keys:
            st = strata[key]
            st.calls += len(set(b_item) & set(c_item))
            st.call_disagreements += call_changes
            st.items += 1
            st.item_disagreements += b_maj != c_maj
        if b_maj != c_maj:
            report.flipped_items.append(
                {
                    "boundary_id": bid,
                    "category": meta[bid].category,
                    "truth": truth[bid],
                    "baseline": b_maj,
                    "candidate": c_maj,
                }
            )
        b_ok = b_maj == expected[truth[bid]]
        c_ok = c_maj == expected[truth[bid]]
        report.correct_both += b_ok and c_ok
        report.correct_baseline_only += b_ok and not c_ok
        report.correct_candidate_only += c_ok and not b_ok
        report.correct_neither += not (b_ok or c_ok)
        common = {"category": meta[bid].category, "expected_answer": truth[bid]}
        nel_base[(idx, 0)] = {"problem_idx": idx, "repeat": 0, "reward": float(b_ok), **common}
        nel_cand[(idx, 0)] = {"problem_idx": idx, "repeat": 0, "reward": float(c_ok), **common}

    report.strata = dict(sorted(strata.items()))
    discordant = report.correct_baseline_only + report.correct_candidate_only
    if discordant:
        report.mcnemar_p = binomtest(report.correct_baseline_only, discordant, 0.5).pvalue
    report.nel_report = _nel_compare(nel_base, nel_cand)
    return report


def _nel_compare(base: dict, cand: dict) -> dict | None:
    try:
        from nemo_evaluator.engine.comparison import compare_results
    except ImportError:
        return None
    return compare_results(base, cand, test="mcnemar")


def render(report: DriftReport) -> str:
    t = report.call_transitions
    flips = f"DONE→CONTINUE {t[('done', 'continue')]}, CONTINUE→DONE {t[('continue', 'done')]}"
    lines = [
        f"# Drift: `{report.baseline}` → `{report.candidate}`",
        "",
        f"- Paired items: {report.paired_items} (unpaired: {report.unpaired_items})",
        f"- Call-level disagreement: {report.call_disagreement} ({flips})",
        f"- Item-level disagreement (majority decision): {report.item_disagreement}",
        "",
        "## Decision transitions (calls, baseline → candidate)",
        "",
        "| Baseline \\ Candidate | " + " | ".join(DECISIONS) + " |",
        "|---|" + "---|" * len(DECISIONS),
    ]
    for a in DECISIONS:
        lines.append(f"| {a} | " + " | ".join(str(t[(a, b)]) for b in DECISIONS) + " |")
    lines += [
        "",
        "## Disagreement by stratum",
        "",
        "| Stratum | Calls changed | Items changed |",
        "|---|---|---|",
    ]
    for key, st in report.strata.items():
        lines.append(
            f"| {key} | {metrics.Rate(st.call_disagreements, st.calls)} | "
            f"{metrics.Rate(st.item_disagreements, st.items)} |"
        )
    p = "–" if report.mcnemar_p is None else f"{report.mcnemar_p:.3g}"
    lines += [
        "",
        "## Correctness against truth (item majority)",
        "",
        f"Both correct {report.correct_both}, baseline only {report.correct_baseline_only}, "
        f"candidate only {report.correct_candidate_only}, neither {report.correct_neither}. "
        f"Exact McNemar p = {p}.",
    ]
    if report.nel_report is not None:
        lines.append(f"NeMo Evaluator verdict: {report.nel_report.get('verdict')}.")
    if report.flipped_items:
        lines += [
            "",
            "## Flipped items",
            "",
            "| Boundary | Category | Truth | Baseline | Candidate |",
            "|---|---|---|---|---|",
        ]
        for f in report.flipped_items:
            lines.append(
                f"| {f['boundary_id']} | {f['category']} | {f['truth']} | {f['baseline']} | "
                f"{f['candidate']} |"
            )
    return "\n".join(lines) + "\n"


def write(report: DriftReport, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{report.baseline}__vs__{report.candidate}".replace(":", "_")
    md = out_dir / f"{stem}.md"
    md.write_text(render(report), encoding="utf-8", newline="\n")
    if report.nel_report is not None:
        (out_dir / f"{stem}.nel.json").write_text(
            json.dumps(report.nel_report, indent=2), encoding="utf-8", newline="\n"
        )
    return md
