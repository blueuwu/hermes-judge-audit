from __future__ import annotations

import json
from dataclasses import replace

import pytest

from hjr import analysis, drift, enrichment, manifest, metrics
from hjr.config import ROOT
from hjr.enrichment import detection, render, stage_b_tasks, task_rates
from hjr.phase2 import draw_sanity, load_boundaries
from hjr.schemas import BoundaryRecord, RunManifest, VerifierResult, write_jsonl
from tests.factories import make_boundary
from tests.test_metrics import V
from tests.test_phase2 import PLAN, _synthetic

FROZEN = ROOT / "data" / "frozen"
EXCLUDED = FROZEN / "phase1-weak.excluded.json"


def test_legacy_boundary_load_and_serialization_preserve_bytes(tmp_path):
    boundary = make_boundary()
    legacy = boundary.model_dump_json(exclude_none=True)
    assert '"phase"' not in legacy
    path = tmp_path / "legacy.jsonl"
    path.write_text(legacy + "\n", encoding="utf-8", newline="\n")
    before = manifest.sha256_file(path)
    loaded = BoundaryRecord.model_validate_json(legacy)
    assert loaded.phase == "1a"
    write_jsonl(path, [loaded])
    assert manifest.sha256_file(path) == before
    enriched = make_boundary(phase="1b-enrichment")
    assert json.loads(enriched.model_dump_json())["phase"] == "1b-enrichment"
    with pytest.raises(ValueError):
        make_boundary(phase="unknown")


def test_legacy_manifest_load_and_phase_serialization():
    fields = dict(
        run_id="synthetic",
        kind="judge-replay",
        git_sha="g",
        git_dirty=False,
        hermes_sha="h",
        uv_lock_sha256="u",
        inputs={},
        variants=[],
        samples=3,
        judge_config_sha256="j",
        models={},
        seed=1,
        started_at=make_boundary().ts,
    )
    old = RunManifest(**fields).model_dump_json()
    assert '"phase"' not in old
    assert RunManifest.model_validate_json(old).model_dump_json() == old
    assert RunManifest(**fields, phase="1b-enrichment").phase == "1b-enrichment"


def test_replay_manifest_refuses_appending_another_phase(tmp_path):
    fields = dict(
        run_id="synthetic",
        kind="judge-replay",
        git_sha="g",
        git_dirty=False,
        hermes_sha="h",
        uv_lock_sha256="u",
        inputs={},
        variants=[],
        samples=3,
        judge_config_sha256="j",
        models={},
        seed=1,
        started_at=make_boundary().ts,
    )
    previous = RunManifest(**fields)
    (tmp_path / "manifest.json").write_text(previous.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="mix phases"):
        manifest.judge_run_manifest(
            tmp_path,
            git_sha="g",
            git_dirty=False,
            boundaries_path=tmp_path / "missing",
            n_boundaries=0,
            variants=[],
            samples=3,
            arms={},
            judge_config_sha256="j",
            seed=1,
            started_at=previous.started_at,
            phase="1b-enrichment",
        )


def test_ingest_manifest_records_only_nonlegacy_phase(monkeypatch, tmp_path):
    monkeypatch.setattr(manifest, "_provenance", lambda *_: {})
    monkeypatch.setattr(manifest, "_jobs", lambda *_: {})
    monkeypatch.setattr(manifest, "sha256_file", lambda *_: "hash")
    args = (tmp_path, tmp_path, [])
    legacy = manifest.ingest_manifest(*args, boundaries=0, excluded=0)
    enriched = manifest.ingest_manifest(*args, boundaries=0, excluded=0, phase="1b-enrichment")
    assert "phase" not in legacy
    assert enriched["phase"] == "1b-enrichment"


def test_phase2_loader_refuses_mixed_phases(tmp_path):
    path = tmp_path / "synthetic.jsonl"
    plan = replace(PLAN, arms={"weak": replace(PLAN.arms["weak"], boundaries=path)})
    write_jsonl(path, [make_boundary(), make_boundary(phase="1b-enrichment")])
    with pytest.raises(ValueError, match="mix phases"):
        load_boundaries(plan, "weak")


def test_enrichment_scores_never_compute_accuracy():
    boundary = make_boundary(
        boundary_id="n1", phase="1b-enrichment", verifier=VerifierResult(truth_state="not_done")
    )
    scores = metrics.score([V("n1", "done")], metrics.truth_map([boundary]), what="test")
    assert scores.semantic_accuracy is scores.effective_accuracy is scores.strict_accuracy is None
    assert (scores.false_done_effective.k, scores.false_done_effective.n) == (1, 1)


def test_drift_cannot_compute_enrichment_correctness():
    boundary = make_boundary(boundary_id="d1", phase="1b-enrichment")
    baseline = [V("d1", "done", arm="a", variant="prod-plain:flash:head4k")]
    candidate = [V("d1", "done", arm="b", variant="prod-plain:drift:head4k")]
    with pytest.raises(ValueError, match="Phase 1a only"):
        drift.compare([boundary], baseline, candidate)


def test_enrichment_report_is_conditional_and_has_no_formal_phase1a_tests():
    boundaries, verdicts = _synthetic()
    boundaries = {
        a: [b.model_copy(update={"phase": "1b-enrichment"}) for b in rows]
        for a, rows in boundaries.items()
    }
    truth = {a: analysis.truth_from_verifier(rows) for a, rows in boundaries.items()}
    report = analysis.analyse(PLAN, truth, boundaries, verdicts, {})
    assert report.phase == "1b-enrichment"
    assert not report.h1 and not report.h4 and not report.exploratory
    for cell in report.cells.values():
        assert cell.kappa is None
        assert cell.scores.effective_accuracy is None
        with pytest.raises(ValueError, match="accuracy"):
            _ = cell.items[0].correct
    rendered = analysis.render(report)
    assert "DONE given not_done" in rendered
    assert "not-done boundaries across 3 tasks" in rendered
    for forbidden in ("Accuracy", "Semantic acc.", "precision", "PABAK", "prevalence", "H4"):
        assert forbidden not in rendered


def test_mix_is_refused_before_filtering_or_separating_arms():
    old = make_boundary(boundary_id="old", verifier=VerifierResult(truth_state="done"))
    new = make_boundary(boundary_id="new", phase="1b-enrichment")
    with pytest.raises(ValueError, match="mix phases"):
        metrics.truth_map([old, new])
    with pytest.raises(ValueError, match="mix phases"):
        analysis.build_items(
            [], {"old": old, "new": new}, analysis.Truth("verifier", {}), samples=3
        )
    boundaries, verdicts = _synthetic()
    boundaries["weak"] = [
        b.model_copy(update={"phase": "1b-enrichment"}) for b in boundaries["weak"]
    ]
    truth = {a: analysis.truth_from_verifier(rows) for a, rows in boundaries.items()}
    with pytest.raises(ValueError, match="mix phases"):
        analysis.analyse(PLAN, truth, boundaries, verdicts, {})


def test_item_metrics_refuse_mix_even_when_truth_filter_would_remove_it():
    old = analysis.Item("old", "t", "C2", "dev", "done", ("done",))
    new = replace(old, boundary_id="new", phase="1b-enrichment", truth="not_done")
    with pytest.raises(ValueError, match="mix phases"):
        analysis.false_done([old, new], seed="synthetic")
    with pytest.raises(ValueError, match="mix phases"):
        analysis.false_continue([old, new], seed="synthetic")
    with pytest.raises(ValueError, match="mix phases"):
        analysis.paired(
            "test",
            ("old", [old]),
            ("new", [new]),
            lambda i: i.judged_done(),
            seed="synthetic",
            restrict=lambda i: i.truth == "not_done",
        )
    with pytest.raises(ValueError, match="Phase 1a only"):
        draw_sanity(PLAN, {"weak": [make_boundary(phase="1b-enrichment")]})


def _frozen(tmp_path, monkeypatch, name, rows, truth):
    """Synthetic frozen file plus its regraded truth rows (truth: boundary_id -> state)."""
    monkeypatch.setattr(enrichment.regrade, "TRUTH", tmp_path)
    path = tmp_path / "frozen" / f"{name}.jsonl"
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    (tmp_path / f"{name}.jsonl").write_text(
        "\n".join(
            json.dumps({"boundary_id": b, "truth_state": t, "requirements": {}})
            for b, t in truth.items()
        ),
        encoding="utf-8",
    )
    return path


def _row(bid, task, category, truth="not_done", **extra):
    return {
        "boundary_id": bid,
        "task_id": f"hjr/{task}",
        "category": category,
        "split": "dev",
        "verifier": {"truth_state": truth},
        **extra,
    }


def test_phase1a_rates_use_primary_truth():
    rates = {r.task_id: r for r in task_rates(FROZEN / "phase1-weak.jsonl", EXCLUDED)}
    assert len(rates) == 16
    c201 = rates["hjr/c2-01-rename-function"]
    assert (c201.not_done, c201.boundaries + c201.excluded) == (0, 3)
    c403 = rates["hjr/c4-03-cobol-modernization"]
    assert (c403.not_done, c403.boundaries + c403.excluded) == (1, 3)
    assert sum(r.not_done for r in rates.values()) == 1
    assert sum(r.boundaries for r in rates.values()) == 46
    assert sum(r.excluded for r in rates.values()) == 2


def test_rates_override_ingest_truth_and_require_every_row(tmp_path, monkeypatch):
    exclusions = tmp_path / "excluded.json"
    exclusions.write_text(json.dumps([{"trial": "t__a", "reason": "timeout"}]), encoding="utf-8")
    rows = [_row("j/t__b/b01", "t", "C4"), _row("j/o__c/b01", "other", "C1", "done")]
    path = _frozen(tmp_path, monkeypatch, "j", rows, {"j/t__b/b01": "done", "j/o__c/b01": "done"})
    (rate,) = task_rates(path, exclusions)
    assert (rate.boundaries, rate.excluded, rate.not_done) == (1, 1, 0)
    path = _frozen(tmp_path, monkeypatch, "j", rows, {"j/t__b/b01": "not_done"})
    with pytest.raises(ValueError, match="no primary truth row"):
        task_rates(path, exclusions)
    (tmp_path / "j.jsonl").unlink()
    with pytest.raises(ValueError, match="hjr regrade"):
        task_rates(path, exclusions)


def test_detection_probability():
    assert detection(0.2, 20) == pytest.approx(1 - 0.8**20)
    assert detection(0.0, 20) == 0
    with pytest.raises(ValueError):
        detection(0.1, 0)
    rendered = render([], 20, [0.02, 0.05, 0.10, 0.20])
    assert "| 2% | 0.332392 |" in rendered and "| 20% | 0.988471 |" in rendered


def test_stage_b_selects_only_c2_c4_tasks_with_primary_not_done(tmp_path, monkeypatch):
    phase = {"phase": "1b-enrichment"}
    rows = [
        _row("s/a__1/b01", "c2-01-a", "C2", "done", **phase),  # v1 done, primary not done
        _row("s/a__2/b01", "c2-01-a", "C2", "done", **phase),
        _row("s/b__1/b01", "c3-01-b", "C3", "not_done", **phase),  # v1 not done, primary done
        _row("s/c__1/b01", "c4-01-c", "C4", "done", **phase),  # blocked is not not done
        _row("s/d__1/b01", "c1-01-d", "C1", "not_done", **phase),  # outside C2-C4
        _row("s/e__1/b01", "c4-02-e", "C4", "not_done", **phase),
    ]
    truth = {
        "s/a__1/b01": "not_done",
        "s/a__2/b01": "done",
        "s/b__1/b01": "done",
        "s/c__1/b01": "blocked",
        "s/d__1/b01": "not_done",
        "s/e__1/b01": "not_done",
    }
    path = _frozen(tmp_path, monkeypatch, "s", rows, truth)
    assert stage_b_tasks(path) == ["c2-01-a", "c4-02-e"]
    assert stage_b_tasks(path) == stage_b_tasks(path)
    del truth["s/e__1/b01"]
    path = _frozen(tmp_path, monkeypatch, "s", rows, truth)
    with pytest.raises(ValueError, match="no primary truth row"):
        stage_b_tasks(path)
    legacy = [{k: v for k, v in r.items() if k != "phase"} for r in rows]
    path = _frozen(tmp_path, monkeypatch, "s", legacy, truth)
    with pytest.raises(ValueError, match="1b-enrichment"):
        stage_b_tasks(path)
