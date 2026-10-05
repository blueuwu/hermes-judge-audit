"""Human audit tooling on synthetic boundaries and workspaces only."""

from __future__ import annotations

import io
import json
import random
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from hjr import audit, cli, regrade, stats
from hjr.schemas import ControllerVerdict, VerifierResult, write_jsonl
from tests.factories import make_boundary

FINAL = "SECRET-CLAIM: everything is done and verified."
PROSE = "SECRET-PROSE: now I will fix the bug."


@pytest.fixture(autouse=True)
def truth_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(regrade, "TRUTH", tmp_path / "truth")
    return tmp_path / "truth"


def _jsonl(path: Path, docs) -> None:
    path.write_text("".join(json.dumps(d) + "\n" for d in docs), encoding="utf-8")


def _primary(boundaries: Path, rows, override: dict[str, str] | None = None) -> Path:
    """Primary truth rows for a boundaries file: each record's own truth unless overridden."""
    path = regrade.TRUTH / f"{boundaries.stem}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    docs = [
        dict(
            boundary_id=b.boundary_id,
            truth_state=(override or {}).get(b.boundary_id, b.verifier.truth_state),
            requirements=b.verifier.requirements,
            verifier_version="v1",
        )
        for b in rows
    ]
    _jsonl(path, docs)
    return path


BOUNDARY_TS = datetime(2026, 10, 5, 14, 2, 11, tzinfo=UTC)  # make_boundary's default ts
DURING_RUN = BOUNDARY_TS.timestamp() - 30
IMAGE_BUILD = BOUNDARY_TS.timestamp() - 3600


def _tgz(path: Path, files: dict[str, tuple[str, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as tar:
        for name, (text, mtime) in files.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(f"./{name}")
            info.size = len(data)
            info.mtime = int(mtime)
            tar.addfile(info, io.BytesIO(data))


def _trial(tmp: Path, n: int, split: str):
    """One boundary with a trial dir, a snapshot and a seed workspace."""
    trial = f"t1-task__{n:03d}"
    root = tmp / "jobs" / "phase1-weak" / trial
    steps = [
        {"step_id": 1, "source": "user", "message": "Make out.txt say hi."},
        {
            "step_id": 2,
            "source": "agent",
            "message": PROSE,
            "tool_calls": [
                {
                    "tool_call_id": "c1",
                    "function_name": "terminal",
                    "arguments": {"command": "echo hi > out.txt"},
                }
            ],
            "observation": {"results": [{"source_call_id": "c1", "content": "exit 0"}]},
        },
        {"step_id": 3, "source": "agent", "message": FINAL},
        {"step_id": 4, "source": "user", "message": "continue"},
        {"step_id": 5, "source": "agent", "message": "turn two", "tool_calls": []},
    ]
    (root / "agent").mkdir(parents=True)
    (root / "agent" / "trajectory.json").write_text(json.dumps({"steps": steps}))
    _tgz(
        root / "artifacts/logs/artifacts/boundaries/b01.tgz",
        {
            "out.txt": ("hi\n", DURING_RUN),
            "keep.txt": ("same\n", IMAGE_BUILD),
            "src/app.py": ("x = 2\n", DURING_RUN),
            "data/generated.log": ("IMAGE-ONLY-CONTENT\n", IMAGE_BUILD),
        },
    )
    seed = tmp / "tasks" / "t1-task" / "environment" / "workspace"
    seed.mkdir(parents=True, exist_ok=True)
    # Bytes, so the seed has LF endings on every platform, like the committed task seeds
    (seed / "keep.txt").write_bytes(b"same\n")
    (seed / "src").mkdir(exist_ok=True)
    (seed / "src" / "app.py").write_bytes(b"x = 1\n")
    (seed / "gone.txt").write_bytes(b"bye\n")
    return make_boundary(
        boundary_id=f"phase1-weak/{trial}/b01",
        run_id="phase1-weak",
        task_id="hjr/t1-task",
        category="C9",
        split=split,
        turn=1,
        goal="Make out.txt say hi.",
        last_response=FINAL,
        verifier=VerifierResult(truth_state="not_done", requirements={"says_hi": False}),
        tags={"agent_arm": "weak", "trial": trial, "agent_seconds": 60.0},
    )


def _votes(path, rows, decisions):
    docs = []
    for b, ds in zip(rows, decisions, strict=True):
        arm = b.run_id.removeprefix("phase1-")
        for sample, decision in enumerate(ds):
            docs.append(
                dict(
                    boundary_id=b.boundary_id,
                    variant=f"prod-plain:self-{arm}:head4k",
                    sample=sample,
                    arm_id=f"arm-{arm}",
                    sub_arm_id=f"sub-{arm}",
                    decision=decision,
                    reason="HIDDEN-JUDGE-REASON",
                    raw="HIDDEN-JUDGE-RAW",
                )
            )
    path.write_text("".join(json.dumps(d) + "\n" for d in docs), encoding="utf-8")
    return path


def _draw(tmp, rows, decisions, seed=20261001):
    boundaries = tmp / "boundaries.jsonl"
    write_jsonl(boundaries, rows)
    _primary(boundaries, rows)
    verdicts = _votes(tmp / "verdicts.jsonl", rows, decisions)
    log = audit.draw(
        audit.load_metadata([boundaries]),
        [verdicts],
        seed=seed,
        primary_verifier="synthetic-freeze",
    )
    return log, boundaries, verdicts


def _population(a=25, b=40, c=15):
    rows, decisions = [], []
    for s, size in (("A", a), ("B", b), ("C", c)):
        for n in range(size):
            arm = "weak" if n % 2 else "strong"
            truth = "not_done" if s == "A" else "done" if s == "B" else "blocked"
            rows.append(
                make_boundary(
                    boundary_id=f"phase1-{arm}/{s}{n:03}/b01",
                    run_id=f"phase1-{arm}",
                    split="heldout" if n % 3 else "dev",
                    verifier=VerifierResult(truth_state=truth, requirements={"r": truth == "done"}),
                )
            )
            decisions.append(["done"] * 3 if s in {"A", "B"} else ["done", "continue", "blocked"])
    return rows, decisions


@pytest.fixture
def session(tmp_path):
    rows = [_trial(tmp_path, n, "dev" if n < 2 else "heldout") for n in range(3)]
    rows[0] = rows[0].model_copy(
        update={
            "controller_verdict": ControllerVerdict(
                verdict="done", reason="HIDDEN-CONTROLLER-REASON", judge="HIDDEN-JUDGE"
            )
        }
    )
    log, boundaries, _ = _draw(tmp_path, rows, [["done"] * 3] * 3)
    return audit.Session(
        log,
        [boundaries],
        tmp_path / "records.jsonl",
        "auditor",
        workdir=tmp_path / "work",
        jobs=tmp_path / "jobs",
        tasks=tmp_path / "tasks",
    )


class Script:
    def __init__(self, answers):
        self.answers = iter(answers)
        self.said, self.opened = [], []

    def console(self):
        return audit.Console(
            ask=lambda _: next(self.answers), say=self.said.append, open=self.opened.append
        )


def test_draw_named_streams_sorted_pools_and_caps(tmp_path):
    rows, decisions = _population()
    log, _, _ = _draw(tmp_path, rows, decisions)
    for s, cap in audit.CAPS.items():
        stratum = log["strata"][s]
        pool = sorted(b.boundary_id for b in rows if f"/{s}" in b.boundary_id)
        expected = sorted(random.Random(f"20261001:audit-{s.lower()}").sample(pool, cap))
        assert stratum["sample"] == expected
        assert stratum["population"] == pool
        assert stratum["inclusion_probability"] == cap / len(pool)
    log2, _, _ = _draw(tmp_path, rows[::-1], decisions[::-1])
    assert log2 == log
    assert sum(len(s["sample"]) for s in log["strata"].values()) == 60


@pytest.mark.parametrize("sizes", [(20, 30, 10), (2, 1, 0), (0, 0, 0)])
def test_small_strata_taken_whole(tmp_path, sizes):
    rows, decisions = _population(*sizes)
    log, _, _ = _draw(tmp_path, rows, decisions)
    for s in audit.CAPS:
        stratum = log["strata"][s]
        assert stratum["sample"] == stratum["population"]
        assert stratum["inclusion_probability"] == (1 if stratum["sample"] else None)


def test_majority_tie_failures_and_blocked_are_not_done(tmp_path):
    rows = [
        make_boundary(
            boundary_id=f"phase1-weak/x{i}/b01",
            run_id="phase1-weak",
            verifier=VerifierResult(truth_state=t),
        )
        for i, t in enumerate(["done", "not_done", "blocked", "done"])
    ]
    log, _, _ = _draw(
        tmp_path,
        rows,
        [
            ["done", "continue", "blocked"],
            ["done", "done", "continue"],
            ["continue", "continue", "done"],
            ["done", "done", "continue"],
        ],
    )
    assert log["strata"]["A"]["population"] == [b.boundary_id for b in rows[:2]]
    assert log["strata"]["B"]["population"] == [rows[3].boundary_id]
    assert log["strata"]["C"]["population"] == [rows[2].boundary_id]


def test_metadata_excludes_phase1b_and_never_validates_payload(tmp_path):
    rows, ds = _population(1, 1, 1)
    log, boundaries, verdicts = _draw(tmp_path, rows, ds)
    docs = [json.loads(line) for line in boundaries.read_text().splitlines()]
    for doc in docs:
        for field in ("goal", "last_response", "recent_tool_events", "controller_verdict"):
            doc[field] = {"malformed": "SECRET"}
    docs += [
        dict(docs[0], boundary_id="enriched", tags={"phase": "1b-enrichment"}),
        dict(docs[0], boundary_id="enriched2", run_id="phase1b-weak"),
    ]
    boundaries.write_text("".join(json.dumps(d) + "\n" for d in docs))
    assert (
        audit.draw(
            audit.load_metadata([boundaries]),
            [verdicts],
            seed=20261001,
            primary_verifier="synthetic-freeze",
        )
        == log
    )
    assert "SECRET" not in json.dumps(log)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "sample", "identity", "wrong-self"])
def test_rejects_incomplete_or_ambiguous_judge_inputs(tmp_path, mutation):
    rows, ds = _population(2, 1, 1)
    _, boundaries, verdicts = _draw(tmp_path, rows, ds)
    docs = [json.loads(line) for line in verdicts.read_text().splitlines()]
    if mutation == "missing":
        docs.pop()
    elif mutation == "duplicate":
        docs.append(docs[0])
    elif mutation == "sample":
        docs[0]["sample"] = 3
    elif mutation == "identity":
        docs[0]["sub_arm_id"] = "other"
    else:
        docs[0]["variant"] = "prod-plain:self-weak:head4k"
    verdicts.write_text("".join(json.dumps(d) + "\n" for d in docs))
    with pytest.raises(ValueError):
        audit.draw(audit.load_metadata([boundaries]), [verdicts], seed=1, primary_verifier="p")


def test_draw_log_resumable_and_refuses_changed_inputs(tmp_path):
    rows, ds = _population()
    log, boundaries, verdicts = _draw(tmp_path, rows, ds)
    path = tmp_path / "draw.json"
    assert audit.load_or_write_draw(path, log) == log
    content = path.read_bytes()
    assert audit.load_or_write_draw(path, log) == log
    assert path.read_bytes() == content
    changed = audit.draw(
        audit.load_metadata([boundaries]), [verdicts], seed=3, primary_verifier="synthetic-freeze"
    )
    with pytest.raises(ValueError, match="refusing to redraw"):
        audit.load_or_write_draw(path, changed)
    assert path.read_bytes() == content


def test_blind_view_shows_trajectory_verifier_and_diff_hides_judge(session):
    bid = audit.audit_order(session.draw_log)[0]
    view, ws, sha = session.blind_view(bid, "1/3")
    text = view.read_text(encoding="utf-8")
    for visible in (
        FINAL,
        PROSE,
        "says_hi",
        "not_done",
        "Make out.txt say hi.",
        "echo hi > out.txt",
        "exit 0",
        "`gone.txt` (removed)",
        "+x = 2",
    ):
        assert visible in text
    for hidden in ("turn two", "HIDDEN", "Stratum", "phase1-weak", "t1-task", "C9"):
        assert hidden not in text
    assert "IMAGE-ONLY-CONTENT" not in text
    assert "keep.txt" not in text
    assert (ws / "out.txt").exists()
    assert sha == audit._sha(text.encode("utf-8"))


def test_heldout_gate_before_loading_or_extraction(session, monkeypatch):
    bid = next(b for b, i in session.draw_log["items"].items() if i["split"] == "heldout")
    monkeypatch.setattr(audit, "heldout_unlocked", lambda: False)
    session.boundary_paths[0].unlink()
    with pytest.raises(PermissionError, match="repair-freeze-v1"):
        session.blind_view(bid, "3/3")
    assert not session.workdir.exists()


def test_direct_renderer_and_sources_enforce_gate(tmp_path, monkeypatch):
    b = make_boundary(split="heldout")
    monkeypatch.setattr(audit, "heldout_unlocked", lambda: False)
    with pytest.raises(PermissionError):
        audit.sources(b, tmp_path, tmp_path)
    with pytest.raises(PermissionError):
        audit.render_blind(b, audit.Sources(tmp_path, tmp_path, None), tmp_path, "1")


def test_tag_check_is_read_only(monkeypatch):
    calls = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(audit.subprocess, "run", run)
    assert audit.heldout_unlocked()
    assert calls[0][0] == ["git", "rev-parse", "-q", "--verify", "refs/tags/repair-freeze-v1"]


def test_run_gate_reason_fix_provenance_and_resume(session, monkeypatch):
    monkeypatch.setattr(audit, "heldout_unlocked", lambda: False)
    script = Script(["invalid", "o", "w", "y", "", "", "n", "", "bad check", "fix commit"])
    assert audit.run_pass(session, script.console()) == 2
    records = audit.load_records(session.records_path)
    assert records[1].verifier_correct == "no"
    assert records[1].reason == "bad check" and records[1].fix == "fix commit"
    assert all(
        r.annotator == "auditor" and r.ts.tzinfo and len(r.view_sha256) == 64 for r in records
    )
    assert any("Held-out audit waits" in line for line in script.said)
    original = session.records_path.read_bytes()
    assert audit.run_pass(session, Script([]).console()) == 0
    monkeypatch.setattr(audit, "heldout_unlocked", lambda: True)
    assert audit.run_pass(session, Script(["y", "", ""]).console()) == 1
    assert session.records_path.read_bytes().startswith(original)
    assert len(audit.load_records(session.records_path)) == 3
    assert audit.run_pass(session, Script([]).console()) == 0


def test_quit_mid_item_restarts_without_partial_record(session):
    assert audit.run_pass(session, Script(["n", "reason", "q"]).console()) == 0
    assert not session.records_path.exists()
    assert audit.run_pass(session, Script(["y", "", "", "q"]).console()) == 1
    assert len(audit.load_records(session.records_path)) == 1


def test_record_validation_duplicates_and_report_provenance(session):
    bid = audit.audit_order(session.draw_log)[0]
    with pytest.raises(ValidationError, match="reason"):
        session.record(bid, "no", " ", "", "hash")
    rec = session.record(bid, "yes", "", "", "hash")
    original = session.records_path.read_bytes()
    with pytest.raises(ValueError, match="already audited"):
        session.record(bid, "no", "bad", "", "hash")
    assert session.records_path.read_bytes() == original
    for wrong in (
        rec.model_copy(update={"draw_sha256": "wrong"}),
        rec.model_copy(update={"boundary_id": "unsampled"}),
    ):
        with pytest.raises(ValueError):
            audit.report(session.draw_log, [wrong])
    with pytest.raises(ValueError, match="duplicate"):
        audit.report(session.draw_log, [rec, rec])


def test_report_counts_inclusion_and_wilson(tmp_path):
    rows, ds = _population()
    log, _, _ = _draw(tmp_path, rows, ds)
    records = []
    order = audit.audit_order(log)
    for n, bid in enumerate(order):
        records.append(
            audit.AuditRecord(
                boundary_id=bid,
                verifier_correct="no" if n % 3 == 0 else "yes",
                reason="reason",
                order_index=n,
                view_sha256="hash",
                draw_sha256=audit._digest(log),
                primary_verifier=log["primary_verifier"],
                annotator="a",
                ts=datetime.now(UTC),
            )
        )
    text = audit.report(log, records)
    for stratum in log["strata"].values():
        got = [r for r in records if r.boundary_id in stratum["sample"]]
        k, n = sum(r.verifier_correct == "no" for r in got), len(got)
        lo, hi = stats.wilson(k, n)
        assert f"[{lo:.4f}, {hi:.4f}]" in text
        assert f"{stratum['inclusion_probability']:.6f}" in text
    empty = audit.report(log, [])
    assert "| 0 | 0 |" in empty and "provisional" in empty
    assert "Phase 1b is excluded" in text


def test_cli_draw_and_report_with_synthetic_178_items(tmp_path, capsys):
    rows, ds = _population(40, 100, 38)
    _, boundaries, verdicts = _draw(tmp_path, rows, ds)
    path = tmp_path / "draw.json"
    assert (
        cli.main(
            [
                "audit",
                "draw",
                "--boundaries",
                str(boundaries),
                "--verdicts",
                str(verdicts),
                "--draw",
                str(path),
                "--primary-verifier",
                "test-freeze",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        cli.main(
            ["audit", "report", "--draw", str(path), "--records", str(tmp_path / "records.jsonl")]
        )
        == 0
    )
    assert "| B | 100 | 30 | 0 | 0 |" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["label"])


def test_effective_fallbacks_no_call_and_other_cells(tmp_path):
    rows, ds = _population(1, 1, 1)
    _, boundaries, verdicts = _draw(tmp_path, rows, ds)
    docs = [json.loads(line) for line in verdicts.read_text().splitlines()]
    for i, outcome in enumerate(("parse_failed", "format_violation", "no_call")):
        docs[i].update(outcome=outcome, decision="continue")
        if outcome == "no_call":
            docs[i]["sub_arm_id"] = ""
    docs.append(dict(docs[3], variant="prod-plain:flash:head4k", decision="blocked"))
    verdicts.write_text("".join(json.dumps(d) + "\n" for d in docs))
    log = audit.draw(audit.load_metadata([boundaries]), [verdicts], seed=1, primary_verifier="p")
    assert log["strata"]["A"]["population"] == []
    assert rows[0].boundary_id in log["strata"]["C"]["population"]


def test_changed_requirement_grade_cannot_resume_even_if_truth_is_unchanged(session):
    truth = regrade.TRUTH / f"{session.boundary_paths[0].stem}.jsonl"
    docs = [json.loads(line) for line in truth.read_text().splitlines()]
    for doc in docs:
        doc["requirements"]["says_hi"] = True
    _jsonl(truth, docs)
    bid = audit.audit_order(session.draw_log)[0]
    with pytest.raises(ValueError, match="metadata differs"):
        session.blind_view(bid, "1/3")
    assert not session.workdir.exists()


def test_strata_and_view_use_primary_truth_not_the_frozen_v1_truth(tmp_path):
    rows, ds = _population(1, 1, 1)
    log, boundaries, verdicts = _draw(tmp_path, rows, ds)
    flipped = {b.boundary_id: "done" for b in rows if b.verifier.truth_state == "not_done"}
    _primary(boundaries, rows, flipped)
    relog = audit.draw(audit.load_metadata([boundaries]), [verdicts], seed=1, primary_verifier="p")
    for bid in flipped:
        assert relog["items"][bid]["verifier"]["truth_state"] == "done"
        assert bid in log["strata"]["A"]["population"]
        assert bid in relog["strata"]["B"]["population"]


def test_a_boundary_without_primary_truth_is_refused(tmp_path):
    rows, ds = _population(1, 1, 1)
    _, boundaries, _ = _draw(tmp_path, rows, ds)
    (regrade.TRUTH / f"{boundaries.stem}.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="no primary truth row"):
        audit.load_metadata([boundaries])
