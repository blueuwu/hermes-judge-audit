from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hjr import metrics
from hjr.arms import MixedArmError
from hjr.schemas import AttemptRecord, JudgeVerdict
from tests.factories import make_boundary

TS = datetime(2026, 10, 1, tzinfo=UTC)
TRUTH = {"d1": "done", "d2": "done", "n1": "not_done", "n2": "not_done", "b1": "blocked"}


def V(bid, decision, outcome="parsed", *, arm="a", sub="s", variant="v", sample=0):
    return JudgeVerdict(
        boundary_id=bid,
        variant=variant,
        sample=sample,
        arm_id=arm,
        sub_arm_id="" if outcome == "no_call" else sub,
        outcome=outcome,
        verdict=decision,
        decision=decision,
        reason="r",
        parse_failed=outcome == "parse_failed",
        format_violation="unknown_label" if outcome == "format_violation" else None,
        raw="x",
        judge_model="m",
        prompt_sha256="0" * 64,
        ts=TS,
    )


def test_three_accuracies_and_rates():
    rows = [
        V("d1", "done"),  # correct
        V("d2", "continue", "parse_failed"),  # fail-open on a done item: wrong in every mode
        # fail-open on a not-done item: right only under effective scoring
        V("n1", "continue", "parse_failed"),
        V("n2", "continue", "format_violation"),  # same, via an unknown label
        V("b1", "done"),  # false DONE on blocked
    ]
    s = metrics.score(rows, TRUTH, what="t")
    assert (s.semantic_accuracy.k, s.semantic_accuracy.n) == (1, 2)
    assert (s.effective_accuracy.k, s.effective_accuracy.n) == (3, 5)
    assert (s.strict_accuracy.k, s.strict_accuracy.n) == (1, 5)
    assert (s.parse_failures.k, s.parse_failures.n) == (2, 5)
    assert (s.format_violations.k, s.format_violations.n) == (1, 5)
    # Fail-open hides false DONE: effective counts 1/3, semantic 1/1.
    assert (s.false_done_effective.k, s.false_done_effective.n) == (1, 3)
    assert (s.false_done_semantic.k, s.false_done_semantic.n) == (1, 1)
    assert (s.false_continue_effective.k, s.false_continue_effective.n) == (1, 2)


def test_no_call_counts_in_effective_but_not_semantic_or_format_rates():
    rows = [V("n1", "continue", "no_call"), V("d1", "done")]
    s = metrics.score(rows, TRUTH, what="t")
    assert s.model_calls == 1
    assert (s.semantic_accuracy.n, s.effective_accuracy.n) == (1, 2)
    assert s.parse_failures.n == 1


def test_refuses_to_pool_arms_sub_arms_or_variants():
    with pytest.raises(MixedArmError):
        metrics.score([V("d1", "done"), V("d2", "done", arm="b")], TRUTH, what="t")
    with pytest.raises(MixedArmError):
        metrics.score([V("d1", "done"), V("d2", "done", sub="s2")], TRUTH, what="t")
    with pytest.raises(MixedArmError):
        metrics.score([V("d1", "done"), V("d2", "done", variant="w")], TRUTH, what="t")


def test_probe_items_cannot_enter_accuracy():
    with pytest.raises(ValueError):
        metrics.truth_map([make_boundary(split="probe")])


def test_missing_truth_raises():
    with pytest.raises(KeyError):
        metrics.score([V("zz", "done")], TRUTH, what="t")


def test_transport_stats_counts_unresolved_calls():
    def A(bid, n, status, err=""):
        return AttemptRecord(
            boundary_id=bid,
            variant="v",
            sample=0,
            arm_id="a",
            attempt=n,
            status=status,
            error_type=err,
            http_status=429 if err else None,
            retryable=bool(err),
            ts=TS,
        )

    attempts = [
        A("d1", 1, "error", "RateLimitError"),
        A("d1", 2, "ok"),
        A("d2", 1, "error", "RateLimitError"),
        A("d2", 2, "error", "APITimeoutError"),
    ]
    t = metrics.transport_stats(attempts, [V("d1", "done")], variant="v")
    assert (t.attempts, t.errors, t.unresolved_calls) == (4, 3, 1)
    assert t.by_type == {"RateLimitError": 2, "APITimeoutError": 1}


def test_rate_formatting():
    assert str(metrics.Rate(1, 4)) == "1/4 (25.0%)"
    assert str(metrics.Rate(0, 0)) == "–"
