"""The frozen Phase 2 plan, and the analysis on synthetic verdicts (no model calls)."""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from hjr import analysis, judge
from hjr.arms import MixedArmError
from hjr.config import load_judge_config
from hjr.phase2 import cell_of, draw_sanity, load_plan, resolve
from hjr.schemas import JudgeVerdict, VerifierResult
from tests.factories import make_boundary

PLAN = load_plan()
CFG = load_judge_config()
TS = datetime(2026, 10, 3, tzinfo=UTC)


# ── Plan ──────────────────────────────────────────────────────────────


def test_self_resolves_per_arm_and_back():
    assert str(resolve("prod-plain:self:head4k", "weak")) == "prod-plain:self-weak:head4k"
    assert str(resolve("prod-plain:self:head4k", "strong")) == "prod-plain:self-strong:head4k"
    assert cell_of("prod-plain:self-strong:head4k") == "prod-plain:self:head4k"
    assert cell_of("repair-v1:flash:evidence") == "repair-v1:flash:evidence"


def test_plan_cells_and_models_exist():
    assert PLAN.samples == 3
    for arm in PLAN.arms:
        for v in PLAN.variants(arm):
            CFG.model(v.model)
    assert "prod-contract" not in " ".join(PLAN.cells)  # no G-contract boundaries in Phase 1


def test_self_cells_judge_only_their_own_arm():
    for arm in PLAN.arms:
        selfs = {v.model for v in PLAN.variants(arm) if v.model.startswith("self-")}
        assert selfs == {f"self-{arm}"}
        assert CFG.self_of[f"self-{arm}"] == arm


def test_headtail_cell_is_identical_on_short_synthetic_boundaries():
    ((cell, same),) = PLAN.identical.items()
    for arm in PLAN.arms:
        a, b = resolve(cell, arm), resolve(same, arm)
        for boundary in [make_boundary(last_response="x" * n) for n in (0, 1959, 2757, 4000)]:
            assert judge.build_messages(
                boundary, prompt=a.prompt, view=a.view
            ) == judge.build_messages(boundary, prompt=b.prompt, view=b.view)


# Derived seed and first draw of every stream still in use, recorded before the label streams
# were retired (prereg Amendment 1). Removing a stream must not shift any of these.
STREAMS = {
    "sanity": ("20261001:harness-sanity", 0.730665052162665),
    "bootstrap": ("20261001:bootstrap", 0.4382615191779776),
}


@pytest.mark.parametrize("stream", sorted(STREAMS))
def test_remaining_seed_streams_are_unchanged(stream):
    seed, first = STREAMS[stream]
    assert PLAN.seed(stream) == seed
    assert random.Random(PLAN.seed(stream)).random() == first


def test_sanity_subset_draw_is_deterministic_and_stratified():
    boundaries = {
        arm: [
            make_boundary(
                boundary_id=f"{arm}/b{k}",
                verifier=VerifierResult(truth_state="not_done" if k < 8 else "done"),
            )
            for k in range(20)
        ]
        for arm in PLAN.arms
    }
    drawn = draw_sanity(PLAN, boundaries)
    assert drawn == draw_sanity(PLAN, boundaries)
    for arm in PLAN.arms:
        rows = {b.boundary_id: b for b in boundaries[arm]}
        neg = [i for i in drawn[arm] if rows[i].verifier.truth_state != "done"]
        assert len(drawn[arm]) == PLAN.sanity["per_arm"] and len(neg) == PLAN.sanity["not_done"]


def test_repair_prompt_puts_static_instructions_first():
    messages = judge.build_messages(make_boundary(), prompt="repair-v1", view="evidence")
    system, user = (m["content"] for m in messages)
    assert "Wrote hello.txt." not in system and "hello.txt" not in system
    assert user.startswith("Goal:\nWrite hello.txt") and "Wrote hello.txt." in user


# ── Items ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "decisions, expected",
    [
        (("done", "done", "continue"), "done"),
        (("continue", "blocked", "continue"), "continue"),
        (("done", "continue", "blocked"), "tie"),
        (("blocked",), "blocked"),
        ((), "tie"),
    ],
)
def test_item_decision_needs_two_of_three(decisions, expected):
    assert analysis.item_decision(decisions) == expected


def _item(bid, task, truth, decisions, split="heldout", category="C2"):
    return analysis.Item(bid, task, category, split, truth, tuple(decisions))


def test_a_tie_is_not_done_and_never_correct():
    i = _item("b", "t", "blocked", ["done", "continue", "blocked"])
    assert not i.judged_done() and not i.correct
    assert not _item("b", "t", "done", ["done", "continue", "blocked"]).judged_done()


def test_first_sample_sensitivity():
    i = _item("b", "t", "not_done", ["done", "continue", "continue"])
    assert not i.judged_done() and i.judged_done(first_only=True)


def test_false_done_and_false_continue_rates():
    items = [_item(f"n{k}", f"t{k % 3}", "not_done", ["done"] * 3) for k in range(4)]
    items += [_item("x", "t9", "blocked", ["blocked"] * 3)]
    items += [_item(f"d{k}", f"t{k}", "done", ["continue"] * 3) for k in range(2)]
    items += [_item(f"e{k}", f"t{k}", "done", ["done"] * 3) for k in range(6)]
    fd = analysis.false_done(items, seed="s")
    fc = analysis.false_continue(items, seed="s")
    assert (fd.k, fd.n, fc.k, fc.n) == (4, 5, 2, 8)
    assert fd.render() == "4/5"  # under 20 items: counts only
    diff = analysis.fd_minus_fc(items, seed="s")
    assert diff.estimate == pytest.approx(4 / 5 - 2 / 8)


def test_paired_comparison_counts_discordant_items_on_the_shared_subset():
    base = [_item(f"b{k}", f"t{k}", "not_done", ["done"] * 3) for k in range(6)]
    cand = [_item(f"b{k}", f"t{k}", "not_done", ["continue"] * 3) for k in range(5)]
    cand.append(_item("b5", "t5", "not_done", ["done"] * 3))
    p = analysis.paired("x", ("base", base), ("cand", cand), lambda i: i.judged_done(), seed="s")
    assert (p.n, p.test.b, p.test.c) == (6, 5, 0)
    assert p.delta.estimate == pytest.approx(-5 / 6)
    assert p.verdict() == "no detectable difference at n = 6"


# ── End to end on synthetic verdicts ─────────────────────────────────


def _verdict(bid, variant, sample, decision, arm_id):
    return JudgeVerdict(
        boundary_id=bid,
        variant=variant,
        sample=sample,
        arm_id=arm_id,
        sub_arm_id="sub",
        outcome="parsed",
        verdict=decision,
        decision=decision,
        reason="r",
        parse_failed=False,
        raw="{}",
        judge_model="m",
        prompt_sha256="h",
        ts=TS,
    )


def _synthetic():
    boundaries, verdicts = {}, {}
    for arm in PLAN.arms:
        rows = []
        for k in range(6):
            truth = "not_done" if k < 3 else "done"
            rows.append(
                make_boundary(
                    boundary_id=f"{arm}/t{k}/b01",
                    task_id=f"t{k}",
                    split="heldout" if k % 2 else "dev",
                    verifier=VerifierResult(truth_state=truth),
                    tags={"agent_arm": arm},
                )
            )
        boundaries[arm] = rows
        vs = []
        for cell in PLAN.cells:
            variant = resolve(cell, arm)
            arm_id = CFG.model(variant.model).arm_id
            for b in rows:
                # The repair says continue on everything; the rest say done on everything.
                decision = "continue" if variant.prompt == "repair-v1" else "done"
                vs += [_verdict(b.boundary_id, str(variant), s, decision, arm_id) for s in range(3)]
        verdicts[arm] = vs
    return boundaries, verdicts


def test_analysis_end_to_end_reports_each_arm_and_the_planned_family():
    boundaries, verdicts = _synthetic()
    truth = {a: analysis.truth_from_verifier(boundaries[a]) for a in PLAN.arms}
    report = analysis.analyse(PLAN, truth, boundaries, verdicts, {})
    c = report.cells[("weak", "prod-plain:self:head4k")]
    assert c.variant == "prod-plain:self-weak:head4k"
    assert (c.false_done.k, c.false_done.n, c.false_continue.k) == (3, 3, 0)
    assert len(report.h4) == 4 and all(p.p_holm is None or p.p_holm >= p.test.p for p in report.h4)
    text = analysis.render(report)
    assert "## Arm: weak" in text and "## Arm: strong" in text
    assert "no detectable difference at n =" in text
    assert "H4 not met" in text


def test_analysis_refuses_variants_outside_the_plan():
    boundaries, verdicts = _synthetic()
    stray = verdicts["weak"][0].model_copy(update={"variant": "prod-plain:self-strong:head4k"})
    verdicts["weak"].append(stray)
    truth = {a: analysis.truth_from_verifier(boundaries[a]) for a in PLAN.arms}
    with pytest.raises(ValueError, match="outside the plan"):
        analysis.analyse(PLAN, truth, boundaries, verdicts, {})


def test_analysis_refuses_mixed_judge_arms_in_one_cell():
    boundaries, verdicts = _synthetic()
    first = verdicts["weak"][0]
    verdicts["weak"][0] = first.model_copy(update={"arm_id": "other"})
    truth = {a: analysis.truth_from_verifier(boundaries[a]) for a in PLAN.arms}
    with pytest.raises(MixedArmError):
        analysis.analyse(PLAN, truth, boundaries, verdicts, {})


@pytest.mark.parametrize(
    "decisions, expected",
    [
        (("done", "continue", "blocked"), "tie"),
        (("done", "continue", ""), "tie"),
        (("continue", "", ""), "tie"),
        (("", "", ""), "tie"),
        (("done", "done", ""), "done"),
        (("blocked", "blocked", "continue"), "blocked"),
    ],
)
def test_exploratory_majority_counts_only_parsed_votes(decisions, expected):
    assert analysis.parsed_majority(_item("b", "t", "done", decisions)) == expected


@pytest.mark.parametrize(
    "votes, expected",
    [
        (("blocked", "blocked", None), "blocked"),
        (("done", None, None), "tie"),
        (("done", "blocked", None), "tie"),
    ],
    ids=["two-matching-one-failure", "one-parsed-two-failures", "one-vs-one-one-failure"],
)
def test_exploratory_scheduled_majority_with_failed_outcomes(votes, expected):
    rows = [
        _verdict("b", "v", s, vote or "done", "a").model_copy(
            update={"outcome": "parsed" if vote else "parse_failed"}
        )
        for s, vote in enumerate(votes)
    ]
    (item,) = analysis.precision_recall_items(
        rows, {"b": make_boundary(boundary_id="b")}, analysis.Truth("verifier", {"b": "done"})
    )
    assert analysis.parsed_majority(item) == expected


def test_exploratory_parse_failure_counts_and_rendering():
    # Four Phase 1a items: fully parsed, three non-parsed outcomes, one missing
    # slot, and all three slots missing. The enrichment failures are excluded.
    boundaries = {
        bid: make_boundary(boundary_id=bid, phase=phase)
        for bid, phase in (
            ("parsed", "1a"),
            ("failed", "1a"),
            ("partial", "1a"),
            ("absent", "1a"),
            ("enriched", "1b-enrichment"),
        )
    }
    rows = []
    for bid, outcomes in (
        ("parsed", ("parsed",) * 3),
        ("failed", ("parse_failed", "format_violation", "no_call")),
        ("partial", ("parsed",) * 2),
        ("enriched", ("no_call",) * 3),
    ):
        for sample, outcome in enumerate(outcomes):
            # The outcome, not the effective decision or parse_failed flag, governs failures.
            rows.append(
                _verdict(bid, "v", sample, "done", "a").model_copy(update={"outcome": outcome})
            )
    items = analysis.precision_recall_items(
        rows, boundaries, analysis.Truth("verifier", dict.fromkeys(boundaries, "done"))
    )
    assert analysis.parse_failure_counts(items) == (7, 12, 3)
    enriched = analysis.Item("enriched", "t", "C2", "dev", "done", ("",) * 3, "1b-enrichment")
    assert analysis.parse_failure_counts([*items, enriched]) == (7, 12, 3)
    assert analysis.parse_failure_counts([]) == (0, 0, 0)

    arm_boundaries, verdicts = _synthetic()
    truth = {a: analysis.truth_from_verifier(arm_boundaries[a]) for a in PLAN.arms}
    report = analysis.analyse(PLAN, truth, arm_boundaries, verdicts, {})
    key = ("weak", "prod-plain:self:head4k")
    report.cells[key] = replace(report.cells[key], precision_recall=items)
    section = analysis._render_precision_recall(report)
    weak, strong = section.split("#### Parse failures, arm: weak")[1].split(
        "### Per-class precision/recall, arm: strong"
    )
    assert "| `prod-plain:self-weak:head4k` | 7/12 | 3 |" in weak
    assert "| `prod-plain:self-strong:head4k` | 0/18 | 0 |" in strong
    assert 'outcome is not "parsed", plus missing samples' in section
    assert "at least 2 matching parsed votes out of the 3 scheduled samples" in section
    assert "a failed sample is not a vote" in section


def test_exploratory_wait_merge_failures_and_phase1b_exclusion():
    boundaries = {
        bid: make_boundary(boundary_id=bid, phase=phase)
        for bid, phase in (
            ("wait", "1a"),
            ("failed", "1a"),
            ("missing", "1a"),
            ("enriched", "1b-enrichment"),
        )
    }
    truth = analysis.Truth("verifier", dict.fromkeys(boundaries, "not_done"))
    rows = []
    for bid in ("wait", "failed", "enriched"):
        for sample, decision in enumerate(("continue", "continue", "done")):
            v = _verdict(bid, "v", sample, decision, "a")
            if bid == "wait" and sample == 0:
                v = v.model_copy(update={"verdict": "wait"})
            if bid == "failed" and sample == 0:
                v = v.model_copy(update={"outcome": "parse_failed", "parse_failed": True})
            rows.append(v)
    items = analysis.precision_recall_items(rows, boundaries, truth)
    assert [i.boundary_id for i in items] == ["wait", "failed", "missing"]
    assert [analysis.parsed_majority(i) for i in items] == ["continue", "tie", "tie"]
    assert items[0].decisions == ("continue", "continue", "done")
    block = analysis.precision_recall_block(items, "v")
    assert "1/1 (Wilson 95% 20.7%–100.0%)" in block[2]
    assert block[2].endswith("| 2 |  |")
    assert block[0].endswith("| 0 | 0/3 |")


def test_exploratory_precision_recall_wilson_and_tie_denominators():
    # DONE: TP 1, predicted 2, actual non-ties 2; BLOCKED: TP 1, predicted 1,
    # actual 2; CONTINUE: TP 1, predicted 2, actual 1. One done-truth tie.
    rows = [
        ("done", ("done",) * 3),
        ("blocked", ("done", "done", "blocked")),
        ("done", ("continue", "continue", "done")),
        ("not_done", ("continue",) * 3),
        ("blocked", ("blocked",) * 3),
        ("done", ("done", "continue", "blocked")),
    ]
    items = [_item(str(k), "t", truth, votes) for k, (truth, votes) in enumerate(rows)]
    block = analysis.precision_recall_block(items, "cell")
    half = "1/2 (Wilson 95% 9.5%–90.5%)"
    one = "1/1 (Wilson 95% 20.7%–100.0%)"
    assert block == [
        f"| `cell` | DONE ↔ done | {half} | {half} | 1 | 3/6 |",
        f"|  | BLOCKED ↔ blocked | {one} | {half} | 0 |  |",
        f"|  | CONTINUE(+WAIT) ↔ not_done | {half} | {one} | 0 |  |",
    ]
    assert analysis._wilson_cell(0, 1) == "0/1 (Wilson 95% 0.0%–79.3%)"
    assert analysis._wilson_cell(0, 0) == "0/0 (Wilson 95% undefined)"
    assert analysis._wilson_cell(20, 20) == "20/20 (Wilson 95% 83.9%–100.0%)"
    enriched = items[0].__class__("extra", "t", "C2", "dev", "done", ("done",) * 3, "1b-enrichment")
    assert analysis.precision_recall_block([*items, enriched], "cell") == block


def test_exploratory_section_is_appended_and_arms_stay_separate():
    boundaries, verdicts = _synthetic()
    truth = {a: analysis.truth_from_verifier(boundaries[a]) for a in PLAN.arms}
    report = analysis.analyse(PLAN, truth, boundaries, verdicts, {})
    text = analysis.render(report)
    heading = "## Exploratory (not pre-registered), see Amendment 2026-10-14"
    assert text.count(heading) == 1
    section = text.split(heading)[1]
    assert section.count("| Cell | Class ↔ truth") == 2
    assert "### Per-class precision/recall, arm: weak" in section
    assert "### Per-class precision/recall, arm: strong" in section
    assert section.count("| 0 | 6/6 |") == 12
    assert "excluded from precision/recall denominators" in section
    report.phase = "1b-enrichment"
    assert heading not in analysis.render(report)
