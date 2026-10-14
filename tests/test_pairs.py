from __future__ import annotations

import json

import pytest

from hjr import pairs, pairs_analysis, stats
from hjr.cli import main
from hjr.judge import apply_view, build_messages, prompt_sha256
from hjr.mutants import Mutant
from hjr.pairs import CLAIM, PairItem, ResponseEdit, read_dev, response_pairs, state_pairs
from hjr.schemas import JudgeVerdict, ToolEvent, VerifierResult, read_jsonl, write_jsonl
from tests.factories import make_boundary

CELL = "prod-plain:flash:head4k"
EVIDENCE = "prod-plain:flash:evidence"


def verdicts(items, decide):
    return [
        JudgeVerdict(
            boundary_id=i.boundary.boundary_id,
            variant=i.cell,
            sample=s,
            arm_id="arm",
            sub_arm_id="sub",
            outcome="parsed",
            verdict=decide(i, s),
            decision=decide(i, s),
            reason="synthetic",
            parse_failed=False,
            raw="{}",
            judge_model="fake",
            prompt_sha256=i.prompt_sha256,
            ts=i.boundary.ts,
        )
        for i in items
        for s in range(3)
    ]


def test_response_pairs_are_deterministic_and_only_change_response():
    base = make_boundary(last_response="Unicode: café. " * 20)
    items = response_pairs([base], [CELL])
    assert items == response_pairs([base], [CELL])
    assert len(items) == 5
    noise = items[:2]
    assert noise[0].prompt_sha256 == noise[1].prompt_sha256
    assert [i.samples for i in noise] == [3, 3]
    null, pre, post = items[2:]
    assert all(i.boundary.response_chars > 4000 for i in (null, pre, post))
    assert (
        apply_view("head4k", null.boundary).encode() == apply_view("head4k", post.boundary).encode()
    )
    assert null.head4k_sha256 == post.head4k_sha256 != pre.head4k_sha256
    for i in items:
        assert i.prompt_sha256 == prompt_sha256(
            build_messages(i.boundary, prompt="prod-plain", view="head4k")
        )
        for field in type(base).model_fields:
            if field not in {"boundary_id", "last_response", "response_chars"}:
                assert getattr(i.boundary, field) == getattr(base, field)


@pytest.mark.parametrize("split", ["heldout", "probe"])
def test_non_dev_refused_before_validation_or_replay(tmp_path, split):
    path = tmp_path / "boundaries.jsonl"
    path.write_text(json.dumps({"split": split, "goal": "SECRET", "bad": "SECRET"}))
    with pytest.raises(ValueError, match="non-dev") as exc:
        read_dev(path)
    assert "SECRET" not in str(exc.value)
    b = make_boundary(split=split)
    with pytest.raises(ValueError, match="split=dev"):
        response_pairs([b], [CELL])
    with pytest.raises(ValueError, match="split=dev"):
        state_pairs(b, tmp_path / "missing", [], [EVIDENCE], FakeExecutor())


def test_reviewed_edits_and_h7_eligibility():
    b = make_boundary(
        verifier=VerifierResult(truth_state="not_done"),
        last_response="Created the file; validation remains incomplete.",
    )
    edits = [
        ResponseEdit(
            boundary_id=b.boundary_id,
            family="h7",
            response=b.last_response + CLAIM,
            rationale="Baseline has no completion claim.",
            claim_free_base=True,
        )
    ]
    items = response_pairs([b], [CELL], edits)
    assert items[-1].family == "h7"
    assert items[-1].boundary.verifier == b.verifier
    with pytest.raises(ValueError, match="not-done"):
        response_pairs(
            [b.model_copy(update={"verifier": VerifierResult(truth_state="done")})], [CELL], edits
        )
    with pytest.raises(ValueError, match="fixed completion claim"):
        response_pairs([b], [CELL], [edits[0].model_copy(update={"response": "Different"})])
    with pytest.raises(ValueError, match="production"):
        response_pairs([b], [EVIDENCE])


class FakeExecutor:
    def __init__(self, *, invisible=False, nonreplayable=False, restore=False):
        self.invisible = invisible
        self.nonreplayable = nonreplayable
        self.restore = restore
        self.calls = []

    def grade(self, task, workspace):
        good = (workspace / "answer").read_text() == "good"
        return VerifierResult(
            truth_state="done" if good else "not_done", requirements={"answer": good, "other": True}
        )

    def replay(self, workspace, events):
        self.calls.append([(e.tool, e.cmd) for e in events])
        bad = (workspace / "answer").read_text() == "bad"
        if self.restore:
            (workspace / "answer").write_text("good")
        if self.nonreplayable or (bad and not self.invisible):
            return [e.model_copy(update={"out_tail": "failure", "exit": 1}) for e in events]
        return list(events)


def state_fixture(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "answer").write_text("good")
    events = [ToolEvent(tool="terminal", cmd=f"check {i}", exit=0, out_tail="ok") for i in range(4)]
    b = make_boundary(
        recent_tool_events=events,
        verifier=VerifierResult(
            truth_state="done",
            requirements={"answer": True, "other": True},
        ),
    )
    m = Mutant(
        b.task_id,
        "req:answer",
        "break answer",
        lambda path: (path / "answer").write_text("bad"),
        ("answer",),
    )
    return b, ws, m


def test_state_replays_exactly_last_three_in_independent_copies(tmp_path):
    b, ws, m = state_fixture(tmp_path)
    b = b.model_copy(update={"task_id": f"hjr/{m.task}"})
    executor = FakeExecutor()
    result = state_pairs(b, ws, [m], [EVIDENCE], executor)
    assert not result.excluded
    null, repeat, mutated = result.items
    assert len(executor.calls) == 2
    assert all(
        cmds == [(e.tool, e.cmd) for e in b.recent_tool_events[-3:]] for cmds in executor.calls
    )
    assert (ws / "answer").read_text() == "good"
    assert null.prompt_sha256 == repeat.prompt_sha256 != mutated.prompt_sha256
    assert null.head4k_sha256 == mutated.head4k_sha256
    assert mutated.boundary.verifier.requirements == {"answer": False, "other": True}
    assert not mutated.evidence_invisible
    with pytest.raises(ValueError, match="evidence-view"):
        state_pairs(b, ws, [m], [CELL], executor)


def test_visibility_uses_truncated_evidence_not_full_recorded_output(tmp_path):
    b, ws, m = state_fixture(tmp_path)
    events = [e.model_copy(update={"out_tail": "old" + "x" * 300}) for e in b.recent_tool_events]
    b = b.model_copy(update={"recent_tool_events": events})

    class TruncatedExecutor(FakeExecutor):
        def replay(self, workspace, events):
            if (workspace / "answer").read_text() == "bad":
                return [e.model_copy(update={"out_tail": "new" + "x" * 300}) for e in events]
            return list(events)

    items = state_pairs(b, ws, [m], [EVIDENCE], TruncatedExecutor()).items
    assert all(i.evidence_invisible for i in items)
    assert items[0].boundary.recent_tool_events != items[-1].boundary.recent_tool_events


@pytest.mark.parametrize(
    "mode,reason",
    [
        ({"nonreplayable": True}, "non-replayable"),
        ({"restore": True}, "replay changed"),
    ],
)
def test_unusable_replays_dropped(tmp_path, mode, reason):
    b, ws, m = state_fixture(tmp_path)
    result = state_pairs(b, ws, [m], [EVIDENCE], FakeExecutor(**mode))
    assert not result.items
    assert reason in result.excluded[0]["reason"]


def test_noop_requirement_mutation_and_missing_events_are_excluded(tmp_path):
    b, ws, m = state_fixture(tmp_path)
    noop = Mutant(m.task, m.id, m.doc, lambda _: None, m.breaks)
    result = state_pairs(b, ws, [noop], [EVIDENCE], FakeExecutor())
    assert "exactly" in result.excluded[0]["reason"]
    short = b.model_copy(update={"recent_tool_events": b.recent_tool_events[:2]})
    assert state_pairs(short, ws, [m], [EVIDENCE], FakeExecutor()).excluded


def test_invisible_state_pairs_are_not_judge_misses(tmp_path):
    b, ws, m = state_fixture(tmp_path)
    items = state_pairs(b, ws, [m], [EVIDENCE], FakeExecutor(invisible=True)).items
    assert all(i.evidence_invisible for i in items)
    report = pairs_analysis.analyse(items, verdicts(items, lambda i, s: "done"), tolerance=None)
    assert not report.comparisons
    assert any("evidence_invisible" in reason for reason in report.excluded)


def synthetic_response_items(n=20):
    rows = [
        make_boundary(
            boundary_id=f"b{i}",
            task_id=f"t{i // 2}",
            last_response="The file exists; a check remains incomplete.",
            verifier=VerifierResult(truth_state="not_done"),
        )
        for i in range(n)
    ]
    edits = [
        ResponseEdit(
            boundary_id=b.boundary_id,
            family=family,
            response=text,
            rationale="Reviewed same facts; claim absent from original.",
            claim_free_base=family == "h7",
            meaning_preserving=family != "h7",
        )
        for b in rows
        for family, text in (
            ("h7", b.last_response + CLAIM),
            ("paraphrase", "A check is still incomplete; the file exists."),
            ("tone", "The file exists. A check remains incomplete."),
        )
    ]
    return response_pairs(rows, [CELL], edits)


def test_h6_h7_e1_and_noise_use_item_majorities_and_paired_clusters():
    items = synthetic_response_items()

    def decision(i, sample):
        done = (i.family == "h6" and i.arm != "pre") or i.family == "h7"
        return "done" if done and sample != 2 else "continue"

    report = pairs_analysis.analyse(items, verdicts(items, decision), tolerance=0.01)
    comparisons = {c.name: c for c in report.comparisons}
    assert report.noise[next(iter(report.noise))][:2] == (0, 20)
    h6, h7 = comparisons["H6"], comparisons["H7"]
    assert (h6.delta.estimate, h6.delta.low, h6.delta.high) == (1, 1, 1)
    assert h6.reading == "H6 holds"
    assert (h7.test.b, h7.test.c) == (0, 20)
    assert h7.p_holm == h7.test.p
    assert h7.delta.estimate == 1
    assert all(
        comparisons[f"E1/{f}"].reading == pairs_analysis.E1_READING for f in ("paraphrase", "tone")
    )
    assert pairs_analysis.analyse(items, verdicts(items, decision), tolerance=0.01) == report
    unset = pairs_analysis.analyse(items, verdicts(items, decision), tolerance=None)
    assert [c.delta for c in unset.comparisons] == [c.delta for c in report.comparisons]
    assert all(
        c.reading == pairs_analysis.E1_READING for c in unset.comparisons if c.name.startswith("E1")
    )


def test_e1_subtracts_each_items_noise_instead_of_unpaired_global_rate():
    items = synthetic_response_items(4)

    def decision(i, sample):
        return (
            "done"
            if (i.family == "noise" and i.arm == "repeat") or i.family == "tone"
            else "continue"
        )

    report = pairs_analysis.analyse(items, verdicts(items, decision), tolerance=0.1)
    e1 = {c.name: c for c in report.comparisons if c.name.startswith("E1")}
    assert e1["E1/paraphrase"].delta.estimate == -1
    assert e1["E1/tone"].delta.estimate == 0
    assert e1["E1/paraphrase"].reading == pairs_analysis.E1_READING
    edits = {family: v for (_, family), v in report.edits.items()}
    assert edits["paraphrase"][:2] == (0, 4) and edits["paraphrase"][3] == 4
    assert edits["tone"][:2] == (4, 4)
    assert "| tone |" in pairs_analysis.render(report)
    assert stats.clopper_pearson(0, 12)[1] == pytest.approx(1 - 0.025 ** (1 / 12))


def test_h8_mcnemar_holm_and_invisible_exclusion(tmp_path):
    b, ws, m = state_fixture(tmp_path)
    items = []
    for i in range(20):
        items.extend(
            state_pairs(
                b.model_copy(update={"boundary_id": f"b{i}", "task_id": m.task}),
                ws,
                [m],
                [EVIDENCE],
                FakeExecutor(),
            ).items
        )
    report = pairs_analysis.analyse(
        items,
        verdicts(items, lambda i, s: "continue" if i.arm == "mutated" else "done"),
        tolerance=None,
    )
    h8 = report.comparisons[0]
    assert h8.name == "H8"
    assert h8.delta.estimate == -1
    assert (h8.test.b, h8.test.c) == (20, 0)
    assert h8.p_holm == stats.mcnemar_exact([True] * 20, [False] * 20).p
    assert next(iter(report.sensitivity.values()))[:2] == (20, 20)
    assert h8.reading == pairs_analysis.H8_READING


def test_repair_comparison_uses_shared_visible_pairs_and_pairs_only_holm(tmp_path, monkeypatch):
    b, ws, m = state_fixture(tmp_path)

    def messages(boundary, *, prompt, view):
        return build_messages(boundary, prompt="prod-plain", view=view)

    # A synthetic future repair prompt exercises the comparison without designing repair-v1.
    monkeypatch.setattr(pairs, "build_messages", messages)
    monkeypatch.setattr(pairs_analysis, "build_messages", messages)
    repair = "repair-v1:flash:evidence"
    items = []
    for i in range(20):
        base = b.model_copy(update={"boundary_id": f"b{i}"})
        cells = [EVIDENCE, repair] if i < 16 else [EVIDENCE]
        items.extend(state_pairs(base, ws, [m], cells, FakeExecutor()).items)
    vs = verdicts(
        items, lambda i, s: "continue" if i.cell == repair and i.arm == "mutated" else "done"
    )
    report = pairs_analysis.analyse(items, vs, tolerance=None)
    comparison = next(c for c in report.comparisons if c.name == "H8/repair sensitivity")
    assert comparison.n == 16
    assert comparison.delta.estimate == 1
    assert (comparison.test.b, comparison.test.c) == (0, 16)
    expected = stats.holm({f"{c.cell}/{c.name}": c.test.p for c in report.comparisons if c.test})
    assert all(c.p_holm == expected[f"{c.cell}/{c.name}"] for c in report.comparisons if c.test)
    assert all(c.reading == pairs_analysis.H8_READING for c in report.comparisons)


def test_task_bootstrap_keeps_repeated_boundaries_in_their_task_clusters():
    items = response_pairs(
        [
            make_boundary(boundary_id=f"b{i}", task_id=task)
            for i, task in enumerate(["a", "a", "a", "b", "c"])
        ],
        [CELL],
    )
    vs = verdicts(
        items,
        lambda item, s: (
            "done"
            if item.family == "h6"
            and (
                item.arm == "null"
                or (item.arm == "post" and item.boundary.task_id != "c")
                or (item.arm == "pre" and item.boundary.task_id != "a")
            )
            else "continue"
        ),
    )
    report = pairs_analysis.analyse(items, vs, tolerance=None)
    h6 = next(c for c in report.comparisons if c.name == "H6")
    rows = [("a", 1.0), ("a", 1.0), ("a", 1.0), ("b", 0.0), ("c", -1.0)]
    expected = stats.cluster_bootstrap(
        rows,
        lambda r: r[0],
        lambda rs: sum(r[1] for r in rs) / len(rs),
        seed=f"{pairs_analysis.global_seed()}:bootstrap:pairs:{h6.cell}:H6",
    )
    assert h6.delta == expected


def test_summary_refuses_duplicates_hash_mismatch_and_mixed_serving_arms():
    items = synthetic_response_items(2)
    vs = verdicts(items, lambda i, s: "done")
    with pytest.raises(ValueError, match="unique samples"):
        pairs_analysis.analyse(items, vs + [vs[0]], tolerance=None)
    with pytest.raises(ValueError, match="hash mismatch"):
        pairs_analysis.analyse(
            items, [vs[0].model_copy(update={"prompt_sha256": "bad"})], tolerance=None
        )
    with pytest.raises(ValueError, match="serving arms"):
        pairs_analysis.analyse(
            items, vs[:-1] + [vs[-1].model_copy(update={"arm_id": "new"})], tolerance=None
        )
    incomplete = pairs_analysis.analyse(items, vs[1:], tolerance=None)
    assert any("incomplete" in x for x in incomplete.excluded)
    with pytest.raises(ValueError, match="tolerance"):
        pairs_analysis.analyse(items, vs, tolerance=-1)


def test_cli_build_and_summary_use_only_synthetic_files(tmp_path, capsys, monkeypatch):
    boundaries, out, judged = [tmp_path / x for x in ("dev.jsonl", "pairs.jsonl", "judge.jsonl")]
    write_jsonl(boundaries, [make_boundary()])
    monkeypatch.setattr(pairs.regrade, "TRUTH", tmp_path)
    row = {"boundary_id": "test/b00", "truth_state": "done", "requirements": {}}
    (tmp_path / "test.jsonl").write_text(json.dumps(row) + "\n")
    assert (
        main(["pairs-build", "--boundaries", str(boundaries), "--out", str(out), "--cell", CELL])
        == 0
    )
    items = list(read_jsonl(out, PairItem))
    assert len(items) == 5
    assert json.loads(out.with_suffix(".excluded.json").read_text()) == []
    write_jsonl(judged, verdicts(items, lambda i, s: "continue"))
    assert main(["pairs-summary", "--items", str(out), "--verdicts", str(judged)]) == 0
    output = capsys.readouterr().out
    assert "Controlled pairs" in output and "H6" in output


def test_read_dev_uses_primary_truth(tmp_path, monkeypatch):
    monkeypatch.setattr(pairs, "FROZEN", tmp_path / "frozen")
    monkeypatch.setattr(pairs.regrade, "TRUTH", tmp_path / "truth")
    path = tmp_path / "dev.jsonl"
    b = make_boundary(
        boundary_id="phase1-weak/t1/b01", verifier=VerifierResult(truth_state="not_done")
    )
    write_jsonl(path, [b])
    with pytest.raises(ValueError, match="hjr regrade"):
        read_dev(path)
    (tmp_path / "truth").mkdir()
    row = {"boundary_id": b.boundary_id, "truth_state": "done", "requirements": {"r1": True}}
    (tmp_path / "truth" / "phase1-weak.jsonl").write_text(json.dumps(row) + "\n")
    [got] = read_dev(path)
    assert got.verifier.truth_state == "done"
    assert got.verifier.requirements == {"r1": True}
    write_jsonl(path, [b, make_boundary(boundary_id="phase1-weak/t1/b02")])
    with pytest.raises(ValueError, match="no primary truth"):
        read_dev(path)


def test_summaries_group_by_the_phase_field_not_a_phase_tag():
    def items_for(phase, n, tags=None):
        rows = [
            make_boundary(
                boundary_id=f"{phase}/b{i}", task_id=f"t{i}", phase=phase, tags=tags or {}
            )
            for i in range(n)
        ]
        return response_pairs(rows, [CELL])

    # Ingest records carry phase as a field and no phase tag; same run and agent model
    phase1a, phase1b = items_for("1a", 2), items_for("1b-enrichment", 3)
    items = phase1a + phase1b
    report = pairs_analysis.analyse(items, verdicts(items, lambda i, s: "done"), tolerance=None)
    assert {label: v[1] for label, v in report.noise.items()} == {
        f"test:None:1a:{CELL}": 2,
        f"test:None:1b-enrichment:{CELL}": 3,
    }
    # A stray phase tag never overrides the field
    tagged = items_for("1a", 2, {"phase": "1b-enrichment"}) + phase1b
    report = pairs_analysis.analyse(tagged, verdicts(tagged, lambda i, s: "done"), tolerance=None)
    assert {label: v[1] for label, v in report.noise.items()} == {
        f"test:None:1a:{CELL}": 2,
        f"test:None:1b-enrichment:{CELL}": 3,
    }
    # Different serving arms in different phases are separate groups, not a refused mix
    mixed = verdicts(phase1a, lambda i, s: "done") + [
        v.model_copy(update={"arm_id": "other"}) for v in verdicts(phase1b, lambda i, s: "done")
    ]
    assert len(pairs_analysis.analyse(items, mixed, tolerance=None).noise) == 2


def test_run_inputs_select_families_and_check_hashes():
    items = response_pairs([make_boundary()], [CELL])
    cell, boundaries = pairs.run_inputs(items, {"noise"})
    assert cell == CELL
    assert [b.boundary_id for b in boundaries] == [
        i.boundary.boundary_id for i in items if i.family == "noise"
    ]
    with pytest.raises(ValueError, match="no pair items"):
        pairs.run_inputs(items, {"h7"})
    with pytest.raises(ValueError, match="one cell"):
        pairs.run_inputs(
            response_pairs([make_boundary()], [CELL, "prod-plain:strong:head4k"]), {"noise"}
        )
    bad = items[0].model_copy(update={"prompt_sha256": "0" * 64})
    with pytest.raises(ValueError, match="hash mismatch"):
        pairs.run_inputs([bad, *items[1:]], {"noise"})


def test_cli_pairs_run_replays_noise_and_refuses_perturbations_before_note(tmp_path, monkeypatch):
    from hjr import cli

    items_path = tmp_path / "pairs.jsonl"
    write_jsonl(items_path, response_pairs([make_boundary()], [CELL]))
    monkeypatch.setattr(cli, "RUNS", tmp_path / "runs")
    calls = []
    monkeypatch.setattr(cli, "cmd_replay", lambda a: calls.append(a) or 0)
    args = ["pairs-run", "--items", str(items_path), "--run-id", "r"]
    with pytest.raises(SystemExit, match="tolerance note"):
        main([*args, "--family", "h6"])
    assert main([*args, "--family", "noise"]) == 0
    (run,) = calls
    assert run.variant == [CELL] and run.samples == 3
    assert [
        b.boundary_id.rsplit("/", 1)[1] for b in read_jsonl(run.boundaries, pairs.BoundaryRecord)
    ] == ["null", "repeat"]
    assert main([*args, "--family", "noise"]) == 0
    with pytest.raises(SystemExit, match="different pair inputs"):
        main([*args, "--family", "h6", "--after-tolerance-note"])


def test_execute_code_timing_is_masked_for_replay_and_visibility(tmp_path):
    b, ws, m = state_fixture(tmp_path)
    tail = '{"status": "success", "output": "ok", "duration_seconds": 0.03, "execution_count": 1}'
    events = [
        ToolEvent(tool="execute_code", cmd=f"run {i}", exit=0, out_tail=tail) for i in range(3)
    ]
    b = b.model_copy(update={"recent_tool_events": events})

    class TimingExecutor(FakeExecutor):
        def replay(self, workspace, events):
            n = 2 if (workspace / "answer").read_text() == "bad" else 1
            return [
                e.model_copy(
                    update={
                        "out_tail": e.out_tail.replace("0.03", f"0.0{n + 5}").replace(
                            '"execution_count": 1', f'"execution_count": {n}'
                        )
                    }
                )
                for e in events
            ]

    result = state_pairs(b, ws, [m], [EVIDENCE], TimingExecutor())
    assert not result.excluded
    assert all(i.evidence_invisible for i in result.items)
    assert len({i.prompt_sha256 for i in result.items}) == 2
    report = pairs_analysis.analyse(
        result.items, verdicts(result.items, lambda i, s: "done"), tolerance=None
    )
    assert not report.comparisons
    assert any("evidence_invisible" in reason for reason in report.excluded)
    other = [e.model_copy(update={"out_tail": tail.replace('"ok"', '"changed"')}) for e in events]

    class OutputExecutor(FakeExecutor):
        def replay(self, workspace, events):
            return other

    assert (
        "non-replayable"
        in state_pairs(b, ws, [m], [EVIDENCE], OutputExecutor()).excluded[0]["reason"]
    )


def test_sign_flip_exact_matches_enumeration_and_rejects_at_five_tasks():
    from fractions import Fraction

    four = stats.sign_flip_exact([Fraction(1)] * 4 + [Fraction(0)] * 8)
    five = stats.sign_flip_exact([Fraction(1, 2)] * 5 + [Fraction(0)] * 7)
    assert (four.positive, four.nonzero, four.p) == (4, 4, 1 / 16)
    assert (five.positive, five.nonzero, five.p) == (5, 5, 1 / 32)
    mixed = stats.sign_flip_exact([Fraction(1), Fraction(1, 3), Fraction(-1, 3)])
    # Sums of the 8 sign assignments of (1, 1/3, 1/3): 5/3, 1, 1, 1/3, -1/3, -1, -1, -5/3.
    assert mixed.p == 3 / 8
    assert stats.sign_flip_exact([Fraction(0)] * 3).p is None


def test_h6_reading_uses_sign_flip_not_bootstrap():
    items = synthetic_response_items()
    tasks = sorted({i.boundary.task_id for i in items if i.family == "h6"})

    def decision(flipping):
        def f(i, sample):
            if i.family == "h6" and i.arm == "pre" and i.boundary.task_id in flipping:
                return "continue"
            return "done"

        return f

    for k, holds in ((4, False), (5, True)):
        report = pairs_analysis.analyse(items, verdicts(items, decision(tasks[:k])), tolerance=None)
        h6 = next(c for c in report.comparisons if c.name == "H6")
        assert (h6.sign_flip.positive, h6.sign_flip.nonzero) == (k, k)
        assert (h6.reading == "H6 holds") is holds
        assert h6.test is None and h6.p_holm is None


def test_reviewed_edits_split_per_arm_without_change():
    data = pairs.ROOT / "data" / "pairs"
    reviewed = (data / "response-edits.draft.jsonl").read_bytes().splitlines(keepends=True)
    split = {
        arm: (data / f"response-edits-{arm}.jsonl").read_bytes().splitlines(keepends=True)
        for arm in ("weak", "strong")
    }
    bases = {}
    for arm, lines in split.items():
        assert len(lines) == 48
        ids = [json.loads(line)["boundary_id"] for line in lines]
        assert all(i.startswith(f"phase1-{arm}/") for i in ids)
        bases[arm] = set(ids)
    assert not bases["weak"] & bases["strong"]
    assert sorted(split["weak"] + split["strong"]) == sorted(reviewed)


def test_state_items_split_per_cell_without_change():
    data = pairs.ROOT / "data" / "pairs"
    for arm in ("weak", "strong"):
        built = (data / f"state-{arm}.jsonl").read_bytes().splitlines(keepends=True)
        parts = sorted(data.glob(f"state-{arm}.*__evidence.jsonl"))
        assert len(parts) == 3
        lines = []
        for part in parts:
            chunk = part.read_bytes().splitlines(keepends=True)
            cells = {json.loads(line)["cell"] for line in chunk}
            assert cells == {part.name.split(".")[1].replace("__", ":")}
            lines += chunk
        assert sorted(lines) == sorted(built)
