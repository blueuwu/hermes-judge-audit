"""Paired constructed-input summaries, kept separate from natural-trajectory rates."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from fractions import Fraction

from hjr import stats
from hjr.config import global_seed
from hjr.judge import Variant, build_messages, prompt_sha256
from hjr.pairs import PairItem, masked_prompt_sha256, require_dev
from hjr.schemas import BoundaryRecord, JudgeVerdict


@dataclass
class Comparison:
    name: str
    cell: str
    n: int
    delta: stats.BootstrapCI
    test: stats.McNemar | None = None
    p_holm: float | None = None
    sign_flip: stats.SignFlip | None = None
    reading: str = ""
    # Holm family: the agent arm's identity and its test family (prereg note of 2026-10-14)
    holm_family: tuple = ()


@dataclass
class PairsReport:
    tolerance: float | None = None
    comparisons: list[Comparison] = field(default_factory=list)
    noise: dict[str, tuple[int, int, tuple[float, float] | None, stats.BootstrapCI]] = field(
        default_factory=dict
    )
    sensitivity: dict[str, tuple[int, int, tuple[float, float] | None, stats.BootstrapCI]] = field(
        default_factory=dict
    )
    # (cell label, family) -> (edit flips vs null, n, Clopper-Pearson CI, paired identical flips)
    edits: dict[tuple[str, str], tuple[int, int, tuple[float, float] | None, int]] = field(
        default_factory=dict
    )
    excluded: list[str] = field(default_factory=list)


# Prereg note of 2026-10-14: at the dev sample size E1, H8 and the repair comparisons are
# reported descriptively. Their numbers are unchanged; only the verdict is withheld.
E1_READING = "descriptive: no inertness claim"
H8_READING = "descriptive: no confirmatory claim"
# Holm family per agent arm: H8 in the three evidence cells and the two repair-v1 comparisons.
H8_FAMILY_SIZE = 5


def _ci(rows: Sequence[tuple[str, float]], stream: str) -> stats.BootstrapCI:
    return stats.cluster_bootstrap(
        rows,
        lambda r: r[0],
        lambda rs: sum(r[1] for r in rs) / len(rs) if rs else None,
        seed=f"{global_seed()}:bootstrap:pairs:{stream}",
    )


def _task_differences(rows: Sequence[tuple[str, float, float]]) -> list[Fraction]:
    """Per task, the mean of (pre-cut flip minus post-cut flip) over its pairs, exactly."""
    by_task: dict[str, list[int]] = defaultdict(list)
    for task, pre, post in rows:
        by_task[task].append(int(pre) - int(post))
    return [Fraction(sum(d), len(d)) for _, d in sorted(by_task.items())]


def _identity(b: BoundaryRecord) -> tuple[str, str | None, str]:
    """Summaries never pool runs, agent models or phases. Phase is the record's own field."""
    return b.run_id, b.agent_model, b.phase


def analyse(
    items: Sequence[PairItem],
    verdicts: Sequence[JudgeVerdict],
    *,
    tolerance: float | None,
) -> PairsReport:
    if tolerance is not None and not 0 <= tolerance <= 1:
        raise ValueError("tolerance must be between 0 and 1")
    by_key = {}
    for item in items:
        require_dev(item.boundary)
        v = Variant.parse(item.cell)
        if item.family.startswith("state/") and v.view != "evidence":
            raise ValueError("hidden-state items cannot enter production cells")
        expected = prompt_sha256(build_messages(item.boundary, prompt=v.prompt, view=v.view))
        head = prompt_sha256(build_messages(item.boundary, prompt=v.prompt, view="head4k"))
        if expected != item.prompt_sha256 or head != item.head4k_sha256:
            raise ValueError("pair input hash mismatch")
        key = (item.boundary.boundary_id, item.cell)
        if key in by_key:
            raise ValueError("duplicate pair item")
        by_key[key] = item
    samples = defaultdict(dict)
    identities = defaultdict(set)
    for v in verdicts:
        key = (v.boundary_id, v.variant)
        if key not in by_key:
            raise ValueError("verdict has no pair item")
        if v.sample not in range(3) or v.sample in samples[key]:
            raise ValueError("expected unique samples 0, 1, 2")
        item = by_key[key]
        if v.prompt_sha256 != item.prompt_sha256:
            raise ValueError("verdict input hash mismatch")
        b = item.boundary
        group = (*_identity(b), item.cell)
        identities[group].add((v.arm_id, v.sub_arm_id))
        samples[key][v.sample] = v.decision == "done"
    if any(len(ids) > 1 for ids in identities.values()):
        raise ValueError("pairs summary refuses to pool serving arms or sub-arms")
    report = PairsReport(tolerance=tolerance)
    grouped = defaultdict(dict)
    arm_of = {}
    for key, item in by_key.items():
        b = item.boundary
        identity = (*_identity(b), item.cell)
        label = ":".join(str(x) for x in identity)
        arm_of[label] = _identity(b)
        if len(samples[key]) != 3:
            report.excluded.append(f"{label} {item.pair_id}/{item.arm}: incomplete samples")
            continue
        grouped[(label, item.pair_id)][item.arm] = (item, sum(samples[key].values()) >= 2)
    observations = defaultdict(list)
    noise = defaultdict(list)
    base_noise = {}
    state = defaultdict(dict)
    for (label, pair_id), arms in grouped.items():
        if "null" not in arms:
            continue
        item, null = arms["null"]
        b = item.boundary
        base_id = pair_id.rsplit("/pairs/", 1)[0]
        if "repeat" in arms:
            repeat_item, repeat = arms["repeat"]
            if item.prompt_sha256 != repeat_item.prompt_sha256:
                raise ValueError("noise-floor inputs must be byte-identical")
            flip = null != repeat
            noise[label].append((b.task_id, float(flip)))
            if item.family == "noise":
                base_noise[(label, base_id)] = (null, flip)
        if item.family == "h6" and {"pre", "post"} <= arms.keys():
            _, pre = arms["pre"]
            post_item, post = arms["post"]
            if item.head4k_sha256 != post_item.head4k_sha256:
                raise ValueError("H6 post-cut input differs from null")
            observations[(label, "H6")].append((b.task_id, float(null != pre), float(null != post)))
        if item.family.startswith("state/") and "mutated" in arms:
            mutated_item, mutated = arms["mutated"]
            invisible = masked_prompt_sha256(item.boundary, item.cell) == masked_prompt_sha256(
                mutated_item.boundary, mutated_item.cell
            )
            if invisible != item.evidence_invisible or invisible != mutated_item.evidence_invisible:
                raise ValueError("incorrect evidence_invisible marker")
            if invisible:
                report.excluded.append(f"{label} {pair_id}: evidence_invisible")
                continue
            observations[(label, "H8")].append((b.task_id, float(null), float(mutated)))
            state[_identity(b)][(pair_id, item.cell)] = (b.task_id, not mutated)
    # Reviewed response edits share the original base's null and independent repeat.
    edit_rows = defaultdict(list)
    for (label, pair_id), arms in grouped.items():
        if "edit" not in arms:
            continue
        item, edited = arms["edit"]
        base_id = pair_id.rsplit("/pairs/", 1)[0]
        if (label, base_id) not in base_noise:
            report.excluded.append(f"{label} {pair_id}: missing paired noise floor")
            continue
        null, flip = base_noise[(label, base_id)]
        if item.family == "h7":
            if item.boundary.verifier.truth_state != "not_done":
                raise ValueError("H7 requires not-done truth")
            values = (float(null), float(edited))
            name = "H7"
        elif item.family in {"paraphrase", "tone"}:
            values = (float(flip), float(null != edited))
            name = f"E1/{item.family}"
        if item.family != "h7":
            # The edit table is for edits meant to leave the decision alone; h7's flip is the
            # effect H7 tests, so it is reported only as H7.
            edit_rows[(label, item.family)].append((null != edited, flip))
        if item.family not in {"h7", "paraphrase", "tone"}:
            continue
        observations[(label, name)].append((item.boundary.task_id, *values))
    for key, flips in sorted(edit_rows.items()):
        k = sum(e for e, _ in flips)
        report.edits[key] = (
            k,
            len(flips),
            stats.clopper_pearson(k, len(flips)),
            sum(f for _, f in flips),
        )
    for label, rows in sorted(noise.items()):
        k = int(sum(r[1] for r in rows))
        report.noise[label] = (
            k,
            len(rows),
            stats.wilson(k, len(rows)),
            _ci(rows, f"{label}:noise"),
        )
    for (label, name), rows in sorted(observations.items()):
        sign = -1 if name == "H6" else 1
        ci = _ci([(task, sign * (y - x)) for task, x, y in rows], f"{label}:{name}")
        test = stats.mcnemar_exact([bool(r[1]) for r in rows], [bool(r[2]) for r in rows])
        # H6 specifies an interval test; E1 specifies equivalence, not McNemar.
        c = Comparison(name, label, len(rows), ci, test if name in {"H7", "H8"} else None)
        c.holm_family = (arm_of[label], name)
        if name.startswith("E1"):
            c.reading = E1_READING
        elif name == "H6":
            # Prereg note of 2026-10-14: the confirmatory rule is an exact one-sided sign-flip
            # test on per-task differences, alpha 0.05; the bootstrap CI is descriptive.
            c.sign_flip = stats.sign_flip_exact(_task_differences(rows))
            p = c.sign_flip.p
            c.reading = "H6 holds" if p is not None and p < 0.05 else "H6 not established"
        elif name == "H8":
            k = sum(not y for _, _, y in rows)
            sensitivity = [(t, float(not y)) for t, _, y in rows]
            report.sensitivity[label] = (
                k,
                len(rows),
                stats.wilson(k, len(rows)),
                _ci(sensitivity, f"{label}:sensitivity"),
            )
        report.comparisons.append(c)
    for identity, rows in sorted(state.items(), key=lambda x: str(x[0])):
        cells = sorted({cell for _, cell in rows})
        for candidate in (c for c in cells if c.startswith("repair-v1:")):
            baseline = "prod-plain:flash:evidence"
            ids = sorted(
                {pid for pid, cell in rows if cell == baseline}
                & {pid for pid, cell in rows if cell == candidate}
            )
            paired = [
                (
                    rows[(pid, baseline)][0],
                    float(rows[(pid, baseline)][1]),
                    float(rows[(pid, candidate)][1]),
                )
                for pid in ids
            ]
            label = ":".join(str(x) for x in (*identity, f"{baseline}->{candidate}"))
            report.comparisons.append(
                Comparison(
                    "H8/repair sensitivity",
                    label,
                    len(paired),
                    _ci([(t, y - x) for t, x, y in paired], label),
                    stats.mcnemar_exact(
                        [bool(x) for _, x, _ in paired], [bool(y) for _, _, y in paired]
                    ),
                    holm_family=(identity, "H8"),
                )
            )
    # Holm per agent arm (prereg note of 2026-10-14): one family of H8 in each evidence cell and
    # the repair-v1 comparisons, and H7 alone. Arms and phases never share a family.
    families = defaultdict(dict)
    for c in report.comparisons:
        if c.test:
            families[c.holm_family][f"{c.cell}/{c.name}"] = c.test.p
    for (arm, name), family in families.items():
        # k is fixed by the prereg; a dropped cell must fail, not shrink the correction.
        if name == "H8" and len(family) != H8_FAMILY_SIZE:
            raise ValueError(
                f"Holm family {arm} has {len(family)} tests, expected {H8_FAMILY_SIZE}"
            )
    adjusted = {k: v for family in families.values() for k, v in stats.holm(family).items()}
    for c in report.comparisons:
        if c.test:
            c.p_holm = adjusted[f"{c.cell}/{c.name}"]
            if c.name.startswith("H8"):
                c.reading = H8_READING
                continue
            ci = c.delta
            c.reading = (
                "difference detected"
                if c.test.detectable
                and ci.low is not None
                and ci.high is not None
                and (ci.low > 0 or ci.high < 0)
                and c.p_holm is not None
                and c.p_holm < 0.05
                else f"no detectable difference at n = {c.n}"
            )
    return report


def _p(c: Comparison) -> str:
    if c.sign_flip:
        f = c.sign_flip
        if f.p is None:
            return "n/a (no task has a nonzero difference)"
        return f"{f.p} (sign-flip, {f.positive}/{f.nonzero} tasks positive)"
    return str(c.test.p) if c.test else "n/a"


def render(report: PairsReport) -> str:
    lines = [
        "# Controlled pairs (constructed inputs only)",
        "",
        "DONE requires 2 of 3 samples. Intervals bootstrap whole tasks (2,000 resamples).",
        "H6 is pre-cut flip minus post-cut flip; H7/H8 are edited minus null DONE rates.",
        "H6 is tested by an exact one-sided sign-flip test on per-task differences (alpha 0.05);",
        "its bootstrap CI is descriptive. Each agent arm is a separate claim.",
        "E1 is edit flip minus paired identical-input flip. Repair compares sensitivity",
        "(mutated not DONE) on the same evidence-visible pairs.",
        "H7's 30-point and H8's 80% reference bars are descriptive, not gates.",
        "E1, H8 and the repair comparisons are descriptive (prereg note of 2026-10-14):",
        "their p-values are shown but carry no verdict.",
        "",
        f"E1 reference tolerance: {report.tolerance if report.tolerance is not None else 'not set'}"
        " (no family is called inert).",
        "",
        "| Cell | Identical-input flips (Wilson) | Task CI |",
        "|---|---|---|",
    ]
    for label, (k, n, ci, clustered) in report.noise.items():
        interval = (
            f"[{clustered.low:.4f}, {clustered.high:.4f}]"
            if n >= stats.MIN_ITEMS_FOR_PERCENT
            else "counts only"
        )
        lines.append(f"| {label} | {stats.fmt_count(k, n, ci)} | {interval} |")
    lines += ["", "| Evidence cell | Sensitivity (Wilson) | Task CI |", "|---|---|---|"]
    for label, (k, n, ci, clustered) in report.sensitivity.items():
        interval = (
            f"[{clustered.low:.4f}, {clustered.high:.4f}]"
            if n >= stats.MIN_ITEMS_FOR_PERCENT
            else "counts only"
        )
        lines.append(f"| {label} | {stats.fmt_count(k, n, ci)} | {interval} |")
    lines += [
        "",
        "| Edit family | Cell | Edit flips vs null (exact 95% CI) | Paired identical-input flips |",
        "|---|---|---|---|",
    ]
    for (label, family), (k, n, ci, noise_k) in report.edits.items():
        interval = f" ({100 * ci[0]:.1f}–{100 * ci[1]:.1f}%)" if ci else ""
        lines.append(f"| {family} | {label} | {k}/{n}{interval} | {noise_k}/{n} |")
    lines += [
        "",
        "| Test | Cell | n | Difference [95% CI] | Exact p | Holm p | Reading |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in report.comparisons:
        d = c.delta
        effect = (
            f"{d.estimate * c.n:+.2f} items "
            f"[{d.low * c.n:+.2f}, {d.high * c.n:+.2f}] (difference × n)"
            if c.n < stats.MIN_ITEMS_FOR_PERCENT and d.low is not None
            else (
                f"{d.estimate:.4f} [{d.low:.4f}, {d.high:.4f}]"
                if d.low is not None
                else "undefined"
            )
        )
        lines.append(
            f"| {c.name} | {c.cell} | {c.n} | {effect} | {_p(c)} | {c.p_holm} | {c.reading} |"
        )
    lines += ["", "Exclusions:", ""] + [f"- {x}" for x in report.excluded]
    return "\n".join(lines) + "\n"
