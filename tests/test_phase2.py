"""The frozen Phase 2 plan, and the analysis on synthetic verdicts (no model calls)."""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from hjr import analysis, judge
from hjr.arms import MixedArmError
from hjr.config import load_judge_config
from hjr.phase2 import cell_of, draw_sanity, load_boundaries, load_plan, resolve
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
        assert {b.tags["agent_arm"] for b in load_boundaries(PLAN, arm)} == {arm}


def test_headtail_cell_is_identical_to_head4k_on_every_phase1_boundary():
    ((cell, same),) = PLAN.identical.items()
    for arm in PLAN.arms:
        a, b = resolve(cell, arm), resolve(same, arm)
        for boundary in load_boundaries(PLAN, arm):
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


def test_sanity_subset_regenerates_from_its_seed():
    drawn = draw_sanity(PLAN, {arm: load_boundaries(PLAN, arm) for arm in PLAN.arms})
    for arm in PLAN.arms:
        assert drawn[arm] == PLAN.sanity_ids(arm)
        rows = {b.boundary_id: b for b in load_boundaries(PLAN, arm)}
        neg = [i for i in drawn[arm] if rows[i].verifier.truth_state != "done"]
        assert len(drawn[arm]) == PLAN.sanity["per_arm"] and len(neg) == PLAN.sanity["not_done"]


def test_repair_prompt_cannot_be_built_before_it_is_designed():
    with pytest.raises(NotImplementedError):
        judge.build_messages(make_boundary(), prompt="repair-v1", view="evidence")


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
