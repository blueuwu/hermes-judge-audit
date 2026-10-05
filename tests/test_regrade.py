from __future__ import annotations

import json

import pytest

from hjr import analysis, regrade, verifier
from hjr.schemas import VerifierResult
from tests.factories import make_boundary

TASK = "c1-01-csv-to-json"


def _boundary(trial: str, truth: str, task: str = TASK):
    return make_boundary(
        boundary_id=f"phase1-weak/{trial}/b01",
        run_id="phase1-weak",
        task_id=f"hjr/{task}",
        verifier=VerifierResult(truth_state=truth),
    )


def _jobs(tmp_path, *boundaries):
    for b in boundaries:
        path = regrade.snapshot_path(b.boundary_id, tmp_path)
        path.parent.mkdir(parents=True)
        path.write_bytes(b"tgz")
    return tmp_path


@pytest.fixture
def grades(monkeypatch):
    """Stand in for the verifier image: grade each snapshot from a queue of truth states."""
    queue: list[verifier.Grade] = []

    def fake(task, snaps, tasks=verifier.TASKS):
        return [queue.pop(0) for _ in snaps]

    monkeypatch.setattr(verifier, "grade_snapshots", fake)
    monkeypatch.setattr(regrade, "check_versions", lambda tasks: None)
    return queue


def test_snapshot_path_follows_the_harness_layout(tmp_path):
    path = regrade.snapshot_path("phase1-weak/c1-01__X/b03", tmp_path)
    assert path == tmp_path / "phase1-weak/c1-01__X/artifacts/logs/artifacts/boundaries/b03.tgz"


def test_regrade_keeps_v1_truth_next_to_the_new_one(tmp_path, grades):
    bs = [_boundary("t__A", "done"), _boundary("t__B", "not_done")]
    grades += [verifier.Grade(True, "done", {"r": True}), verifier.Grade(True, "done", {"r": True})]
    rows = regrade.regrade(bs, _jobs(tmp_path, *bs))
    assert [(r.v1_truth_state, r.truth_state) for r in rows] == [
        ("done", "done"),
        ("not_done", "done"),
    ]
    assert {r.verifier_version for r in rows} == {verifier.version_of(TASK)[0]}


def test_a_v1_task_must_reproduce_its_ingest_truth(tmp_path, grades):
    b = _boundary("t__A", "done")
    grades.append(verifier.Grade(True, "not_done", {"r": False}))
    rows = regrade.regrade([b], _jobs(tmp_path, b))
    assert verifier.version_of(TASK)[0] == "v1"
    assert regrade.not_reproduced(rows) == rows


def test_a_grading_failure_writes_nothing(tmp_path, grades):
    b = _boundary("t__A", "done")
    grades.append(verifier.Grade(False, error="container timed out"))
    with pytest.raises(SystemExit, match="failed to grade"):
        regrade.regrade([b], _jobs(tmp_path, b))


def test_a_missing_snapshot_writes_nothing(tmp_path, grades):
    with pytest.raises(SystemExit, match="1 snapshots missing"):
        regrade.regrade([_boundary("t__A", "done")], tmp_path)


def test_a_verifier_changed_without_a_version_bump_is_refused(monkeypatch):
    monkeypatch.setattr(verifier, "tests_sha", lambda task: "edited")
    with pytest.raises(SystemExit, match="does not match"):
        regrade.check_versions({TASK})


def test_written_truth_is_what_the_analysis_reads(tmp_path, grades, monkeypatch):
    bs = [_boundary("t__A", "done"), _boundary("t__B", "not_done")]
    grades += [verifier.Grade(True, "done", {}), verifier.Grade(True, "done", {})]
    rows = regrade.regrade(bs, _jobs(tmp_path, *bs))
    out = regrade.write("phase1-weak", rows, tmp_path / "truth", tmp_path / "log")
    log = (tmp_path / "log" / "phase1-weak.md").read_text(encoding="utf-8")
    assert "## Changed (1)" in log and "`phase1-weak/t__B/b01`" in log
    assert b"\r\n" not in out.read_bytes()
    monkeypatch.setattr(regrade, "TRUTH", tmp_path / "truth")
    truth = analysis.truth_from_file("data/frozen/phase1-weak.jsonl")
    assert truth.source == "verifier-primary"
    assert truth.states == {"phase1-weak/t__A/b01": "done", "phase1-weak/t__B/b01": "done"}
    assert [json.loads(line)["v1_truth_state"] for line in out.open()] == ["done", "not_done"]


def test_primary_truth_must_exist_before_the_analysis(tmp_path, monkeypatch):
    monkeypatch.setattr(regrade, "TRUTH", tmp_path)
    with pytest.raises(SystemExit, match="hjr regrade"):
        analysis.truth_from_file("data/frozen/phase1-weak.jsonl")
