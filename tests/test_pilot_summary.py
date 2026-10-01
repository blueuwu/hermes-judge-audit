from __future__ import annotations

from datetime import UTC, datetime

from hjr.judge import Variant
from hjr.pilot import build, summarize
from hjr.replay import verdict_path
from hjr.schemas import JudgeVerdict, write_jsonl

TS = datetime(2026, 10, 1, tzinfo=UTC)


def _verdict(boundary_id, variant, sample, decision):
    return JudgeVerdict(
        boundary_id=boundary_id,
        variant=str(variant),
        sample=sample,
        verdict=decision,
        decision=decision,
        reason="r",
        parse_failed=False,
        raw="{}",
        judge_model="m",
        prompt_sha256="0" * 64,
        ts=TS,
    )


def test_oracle_judge_scores_done_rows_only(tmp_path):
    """A judge that always matches truth gets n/n on done rows and 0/n on not-done rows."""
    records = list(build.build())
    variant = Variant.parse("prod-plain:oracle:head4k")
    verdicts = [
        _verdict(
            r.boundary_id, variant, s, "done" if r.verifier.truth_state == "done" else "continue"
        )
        for r in records
        for s in range(3)
    ]
    write_jsonl(verdict_path(tmp_path, variant), verdicts)
    text = summarize.render(records, summarize.load(tmp_path))
    assert "| Control: evidenced done | done | 4/4 |" in text
    assert "| A1 confident false claim | not done | 0/4 |" in text
    assert "| no caveat | done | 4/4 |" in text
    assert "| ~4,500 | not done | 0/4 |" in text
    assert f"| `{variant}` | 48 | 144 | 0 | 0 |" in text


def test_majority_and_flip():
    stats = summarize.ItemStats()
    for d in ("done", "done", "continue"):
        stats.add(_verdict("b", "v", 0, d))
    assert stats.majority_done and stats.flipped
    tie = summarize.ItemStats()
    for d in ("done", "continue"):
        tie.add(_verdict("b", "v", 0, d))
    assert not tie.majority_done
