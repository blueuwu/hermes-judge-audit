"""The blind labelling CLI on a synthetic trial: hiding, order, resume, relabel gate, report."""

from __future__ import annotations

import io
import json
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hjr import label
from hjr.phase2 import load_plan
from hjr.schemas import LabelRecord, VerifierResult
from tests.factories import make_boundary

PLAN = load_plan()
FINAL = "SECRET-CLAIM: everything is done and verified."
PROSE = "SECRET-PROSE: now I will fix the bug."


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


@pytest.fixture
def session(tmp_path):
    rows = [_trial(tmp_path, n, "dev" if n < 2 else "heldout") for n in range(3)]
    order = label.load_or_write_order(tmp_path / "labels" / "order.json", rows, "seed")
    s = label.Session(
        PLAN,
        {b.boundary_id: b for b in rows},
        order,
        tmp_path / "labels" / "labels.jsonl",
        "annotator",
        workdir=tmp_path / "work",
        jobs=tmp_path / "jobs",
        tasks=tmp_path / "tasks",
    )
    return s


class Script:
    def __init__(self, answers):
        self.answers = list(answers)
        self.said = []
        self.opened = []

    def console(self):
        return label.Console(ask=self._ask, say=self.said.append, open=self.opened.append)

    def _ask(self, prompt):
        if not self.answers:
            raise AssertionError(f"unexpected prompt: {prompt}")
        return self.answers.pop(0)


def test_blind_view_hides_agent_messages_verifier_and_names(session):
    bid = session.order[0]
    view, ws, _ = session.blind_view(bid, "1/3")
    text = view.read_text(encoding="utf-8")
    for hidden in (FINAL, PROSE, "turn two", "says_hi", "not_done", "t1-task", "C9", "weak"):
        assert hidden not in text, hidden
    assert "Make out.txt say hi." in text and "echo hi > out.txt" in text and "exit 0" in text
    assert "`out.txt` (added)" in text and "`gone.txt` (removed)" in text
    assert "`src/app.py` (changed)" in text and "+x = 2" in text
    assert "keep.txt" not in text
    # Not in the seed but older than the run: listed from the task image, content not shown
    assert "`data/generated.log` (19 bytes)" in text and "IMAGE-ONLY-CONTENT" not in text
    assert view.parent.name not in bid and (ws / "out.txt").exists()


def test_reveal_shows_agent_messages_and_verifier(session):
    bid = session.order[0]
    b, src, _, _ = session.prepare(bid)
    blind = session.record(bid, "blind", "done", "sure", "x")
    text = label.render_reveal(b, src, blind)
    assert FINAL in text and PROSE in text and "FAIL `says_hi`" in text
    assert "turn two" not in text  # only up to the boundary's turn


def test_order_is_seeded_dev_first_and_checked_on_reload(session, tmp_path):
    rows = list(session.boundaries.values())
    assert session.order == label.load_or_write_order(
        tmp_path / "labels" / "order.json", rows, "seed"
    )
    assert [session.boundaries[b].split for b in session.order] == ["dev", "dev", "heldout"]
    with pytest.raises(RuntimeError):
        label.load_or_write_order(tmp_path / "labels" / "order.json", rows, "other")


def test_first_pass_labels_dev_then_stops_at_the_heldout_gate(session):
    script = Script(["d", "s", "", "", "s", "y", "", "n", "u", "unsure why", "", "s", "x", ""])
    finished = label.run_first_pass(session, script.console(), heldout_open=False)
    assert finished == 2
    recs = label.load_labels(session.labels_path)
    assert [r.stage for r in recs] == ["blind", "adjudicated", "blind", "adjudicated"]
    assert recs[1].label == "done" and recs[1].verifier_correct == "yes"
    assert recs[2].notes == "unsure why" and recs[3].label == "not_done"
    assert any("Held-out ones open once tag" in s for s in script.said)


def test_quit_mid_item_resumes_at_adjudication(session):
    first = Script(["a", "s", "odd workspace", "q"])
    assert label.run_first_pass(session, first.console(), heldout_open=True) == 0
    recs = label.load_labels(session.labels_path)
    assert [(r.stage, r.label) for r in recs] == [("blind", "ambiguous")]
    second = Script(["", "s", "x", "still odd", "q"])
    label.run_first_pass(session, second.console(), heldout_open=True)
    recs = label.load_labels(session.labels_path)
    assert [(r.stage, r.label) for r in recs] == [
        ("blind", "ambiguous"),
        ("adjudicated", "ambiguous"),
    ]


def test_notes_are_required_when_adjudication_changes_the_label(session):
    script = Script(["d", "s", "", "b", "s", "y", "", "blocked after all", "q"])
    label.run_first_pass(session, script.console(), heldout_open=True)
    recs = label.load_labels(session.labels_path)
    assert recs[1].label == "blocked" and recs[1].notes == "blocked after all"


def _rec(bid, stage, value, ts):
    return LabelRecord(
        boundary_id=bid,
        stage=stage,
        label=value,
        confidence="sure",
        order_index=0,
        view_sha256="x",
        annotator="a",
        ts=ts,
    )


def test_relabel_waits_a_day_after_the_first_blind_label():
    t0 = datetime(2026, 10, 3, tzinfo=UTC)
    labels = [_rec("a", "blind", "done", t0), _rec("b", "blind", "done", t0 + timedelta(hours=5))]
    due, waiting = label.relabel_due(["a", "b"], labels, t0 + timedelta(hours=26), 24)
    assert (due, waiting) == (["a"], ["b"])
    labels.append(_rec("a", "relabel", "done", t0 + timedelta(hours=27)))
    assert label.relabel_due(["a", "b"], labels, t0 + timedelta(hours=40), 24) == (["b"], [])


def test_relabel_draw_is_seeded_and_sized():
    order = [f"b{i:03d}" for i in range(178)]
    ids = label.draw_relabel(PLAN, order)
    assert len(ids) == 25 == len(set(ids)) and ids == label.draw_relabel(PLAN, order)


def test_report_counts_intra_rater_agreement_and_ambiguous(session):
    t0 = datetime(2026, 10, 3, tzinfo=UTC)
    a, b, c = session.order
    labels = [
        _rec(a, "blind", "done", t0),
        _rec(a, "adjudicated", "not_done", t0),
        _rec(b, "blind", "blocked", t0),
        _rec(b, "adjudicated", "ambiguous", t0),
        _rec(a, "relabel", "done", t0 + timedelta(days=1)),
        _rec(b, "relabel", "done", t0 + timedelta(days=1)),
    ]
    text = label.report(session.boundaries, labels, [a, b])
    assert "Blind label changed at adjudication: 2" in text
    assert "n = 2: raw agreement 0.50" in text and "intra-rater" in text
    assert f"`{b}`" in text
