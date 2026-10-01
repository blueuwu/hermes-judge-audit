from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hjr import drift
from hjr.arms import MixedArmError
from tests.factories import make_boundary
from tests.test_metrics import V

TS = datetime(2026, 10, 1, tzinfo=UTC)
B = "prod-plain:flash:head4k"
C = "prod-plain:drift:head4k"


def _boundaries():
    return [
        make_boundary(boundary_id="d1", category="A7"),
        make_boundary(boundary_id="n1", category="A1", verifier={"truth_state": "not_done"}),
        make_boundary(boundary_id="n2", category="A1", verifier={"truth_state": "not_done"}),
        make_boundary(
            boundary_id="t1",
            category="TRUNC",
            tags={"scenario": "etl"},
            verifier={"truth_state": "not_done"},
        ),
    ]


def _side(decisions: dict[str, list[str]], variant: str, arm: str):
    return [
        V(bid, d, arm=arm, variant=variant, sample=s)
        for bid, ds in decisions.items()
        for s, d in enumerate(ds)
    ]


def test_counts_flips_strata_and_correctness():
    base = _side(
        {"d1": ["done"] * 3, "n1": ["continue"] * 3, "n2": ["done"] * 3, "t1": ["done"] * 3},
        B,
        "a",
    )
    cand = _side(
        {
            "d1": ["continue"] * 3,
            "n1": ["continue"] * 3,
            "n2": ["continue"] * 3,
            "t1": ["done", "done", "continue"],
        },
        C,
        "b",
    )
    r = drift.compare(_boundaries(), base, cand)
    assert (r.paired_items, r.paired_calls) == (4, 12)
    assert r.call_transitions[("done", "continue")] == 7
    assert r.call_transitions[("continue", "done")] == 0
    assert (r.item_disagreement.k, r.item_disagreement.n) == (2, 4)
    assert r.strata["category=A1"].item_disagreements == 1
    assert r.strata["scenario=etl"].call_disagreements == 1
    # d1: base right, cand wrong. n2: base wrong, cand right.
    assert (r.correct_baseline_only, r.correct_candidate_only) == (1, 1)
    assert r.mcnemar_p == pytest.approx(1.0)
    text = drift.render(r)
    assert "DONE→CONTINUE 7" in text and "| d1 | A7 | done | done | continue |" in text


def test_refuses_different_prompt_or_view_and_same_arm():
    base = _side({"d1": ["done"]}, B, "a")
    with pytest.raises(ValueError):
        drift.compare(
            _boundaries(), base, _side({"d1": ["done"]}, "prod-plain:drift:headtail4k", "b")
        )
    with pytest.raises(ValueError):
        drift.compare(_boundaries(), base, _side({"d1": ["done"]}, C, "a"))


def test_refuses_mixed_sub_arms_within_a_side():
    base = _side({"d1": ["done"]}, B, "a") + [V("n1", "continue", arm="a", sub="s2", variant=B)]
    with pytest.raises(MixedArmError):
        drift.compare(_boundaries(), base, _side({"d1": ["done"]}, C, "b"))


def test_majority_tie():
    assert drift._majority(["done", "continue"]) == "tie"
    assert drift._majority(["done", "done", "continue"]) == "done"


def test_nemo_compare_receives_paired_correctness():
    pytest.importorskip("nemo_evaluator")
    base = _side({"d1": ["done"], "n1": ["done"], "n2": ["done"], "t1": ["done"]}, B, "a")
    cand = _side(
        {"d1": ["done"], "n1": ["continue"], "n2": ["continue"], "t1": ["continue"]}, C, "b"
    )
    r = drift.compare(_boundaries(), base, cand)
    assert r.nel_report["test_used"] == "mcnemar"
    assert r.nel_report["flip_report"]["summary"]["n_paired"] == 4
