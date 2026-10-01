from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from hjr.ingest import ingest_job
from hjr.schemas import JudgeVerdict, ToolEvent, TurnRecord

TASKS = Path(__file__).resolve().parents[1] / "tasks"
TS = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _verdict(boundary_id: str, verdict: str) -> JudgeVerdict:
    return JudgeVerdict(
        boundary_id=boundary_id,
        variant="prod-plain:self-weak:head4k",
        sample=0,
        arm_id="arm",
        sub_arm_id="sub",
        outcome="parsed",
        verdict=verdict,
        decision="done" if verdict == "done" else "continue",
        reason="r",
        parse_failed=False,
        raw="{}",
        judge_model="qwen/qwen3-coder-30b-a3b-instruct",
        prompt_sha256="x",
        ts=TS,
    )


def _turn(trial: str, n: int, verdict: str, action: str, events=()) -> TurnRecord:
    bid = f"job/{trial}/b{n:02d}"
    return TurnRecord(
        boundary_id=bid,
        run_id="job",
        trial=trial,
        task_id="hjr/c3-02-missing-sqlite",
        agent_arm="weak",
        agent_model="qwen/qwen3-coder-30b-a3b-instruct",
        turn=n,
        prompt="p",
        goal="Apply migration 003.",
        last_response="Migration applied.",
        response_chars=18,
        session_id="s1",
        recent_tool_events=list(events),
        snapshot=f"b{n:02d}.tgz",
        controller=_verdict(bid, verdict),
        action=action,
        agent_exit_code=0,
        ts=TS,
    )


def _trial(job: Path, name: str, turns: list[TurnRecord], graded: dict | None) -> None:
    (job / name / "agent").mkdir(parents=True)
    (job / name / "agent" / "turns.jsonl").write_text(
        "".join(t.model_dump_json() + "\n" for t in turns)
    )
    if graded is not None:
        (job / name / "verifier").mkdir()
        (job / name / "verifier" / "boundaries.json").write_text(json.dumps(graded))


def _graded(*truths: str) -> dict:
    return {
        "final": {"truth_state": truths[-1], "requirements": {}},
        "boundaries": [
            {"snapshot": f"b{i:02d}.tgz", "turn": i, "truth_state": t, "requirements": {"x": True}}
            for i, t in enumerate(truths, start=1)
        ],
    }


def test_ingest_joins_turns_with_verifier_truth(tmp_path):
    job = tmp_path / "job"
    curl = ToolEvent(tool="terminal", cmd="curl -s https://example.com", exit=0)
    trial = "c3-02-missing-sqlite__a1"
    turns = [_turn(trial, 1, "continue", "continue"), _turn(trial, 2, "done", "done", [curl])]
    _trial(job, trial, turns, _graded("not_done", "not_done"))
    _trial(
        job,
        "c3-02-missing-sqlite__a2",
        [_turn("c3-02-missing-sqlite__a2", 1, "done", "done")],
        None,
    )
    (job / "config.json").write_text("{}")

    result = ingest_job(job, TASKS, split="dev", hermes_sha="ffc", harbor="0.23.0")

    assert [b.boundary_id for b in result.boundaries] == [
        "job/c3-02-missing-sqlite__a1/b01",
        "job/c3-02-missing-sqlite__a1/b02",
    ]
    false_done = result.boundaries[1]
    assert false_done.controller_verdict.verdict == "done"
    assert false_done.verifier.truth_state == "not_done"
    assert false_done.category == "C3"
    assert false_done.tags["network_tool_use"] == 1
    assert result.boundaries[0].tags["network_tool_use"] == 0
    assert result.excluded == [
        {"trial": "c3-02-missing-sqlite__a2", "reason": "no verifier boundaries.json"}
    ]


def test_ungraded_snapshot_is_excluded_with_reason(tmp_path):
    job = tmp_path / "job"
    trial = "c3-02-missing-sqlite__a1"
    turns = [_turn(trial, 1, "continue", "continue"), _turn(trial, 2, "done", "done")]
    _trial(job, trial, turns, _graded("not_done"))
    result = ingest_job(job, TASKS, split="dev", hermes_sha="ffc", harbor="0.23.0")
    assert len(result.boundaries) == 1
    assert result.excluded == [{"trial": trial, "reason": "snapshot b02.tgz not graded"}]


def test_soak_only_task_is_refused_whole(tmp_path):
    job = tmp_path / "job"
    trial = "s0-01-incident-review__a1"
    soak = {"task_id": "hjr/s0-01-incident-review", "trial": trial}
    turns = [_turn(trial, n, "continue", "continue").model_copy(update=soak) for n in (1, 2)]
    _trial(job, trial, turns, _graded("not_done", "not_done"))
    result = ingest_job(job, TASKS, split="dev", hermes_sha="ffc", harbor="0.23.0")
    assert result.boundaries == []
    assert result.excluded == [{"trial": trial, "reason": "soak-only task (never analysed)"}]
