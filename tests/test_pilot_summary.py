from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hjr.arms import MixedArmError
from hjr.pilot import build, summarize
from hjr.schemas import JudgeVerdict

TS = datetime(2026, 10, 1, tzinfo=UTC)
RECORDS = list(build.build())


def _verdict(
    boundary_id, sample, decision, *, variant="prod-plain:m:head4k", sub="s1", outcome="parsed"
):
    return JudgeVerdict(
        boundary_id=boundary_id,
        variant=variant,
        sample=sample,
        arm_id="a1",
        sub_arm_id=sub,
        outcome=outcome,
        verdict=decision,
        decision=decision,
        reason="r",
        parse_failed=outcome == "parse_failed",
        raw="{}",
        judge_model="m",
        prompt_sha256="0" * 64,
        ts=TS,
    )


def _oracle(**kw):
    return [
        _verdict(r.boundary_id, s, "done" if r.verifier.truth_state == "done" else "continue", **kw)
        for r in RECORDS
        for s in range(3)
    ]


def test_oracle_judge_scores_done_rows_only():
    text = summarize.render(RECORDS, _oracle(), [])
    assert "| Control: evidenced done | done | 4/4 |" in text
    assert "| A1 confident false claim | not done | 0/4 |" in text
    assert "| no caveat | done | 4/4 |" in text
    assert "| ~4,500 | not done | 0/4 |" in text
    assert "| `prod-plain:m:head4k` | 144/144 (100.0%) | 144/144 (100.0%) |" in text
    assert "| `prod-plain:m:head4k` | 48 | 144 | 0 |" in text


def test_reliability_section_comes_first():
    text = summarize.render(RECORDS, _oracle(), [])
    assert text.index("## 1. Reliability") < text.index("## 2. Accuracy")


def test_mixed_sub_arms_refused_unless_split():
    rows = _oracle()
    rows[0] = rows[0].model_copy(update={"sub_arm_id": "s2"})
    with pytest.raises(MixedArmError):
        summarize.render(RECORDS, rows, [])
    text = summarize.render(RECORDS, rows, [], split_sub_arms=True)
    assert "[sub-arm s2]" in text


def test_majority_and_flip():
    stats = summarize.ItemStats()
    for d in ("done", "done", "continue"):
        stats.add(_verdict("b", 0, d))
    assert stats.majority_done and stats.flipped
    tie = summarize.ItemStats()
    for d in ("done", "continue"):
        tie.add(_verdict("b", 0, d))
    assert not tie.majority_done
