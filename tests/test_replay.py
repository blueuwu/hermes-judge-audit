from __future__ import annotations

import json
import threading

import pytest

from hjr.arms import Arm
from hjr.client import Attempt, CompletionResult, TransportError
from hjr.judge import Variant
from hjr.replay import EMPTY_RESPONSE_REASON, load_verdicts, replay, verdict_path
from hjr.schemas import AttemptRecord, DriftIncident, JudgeVerdict, read_jsonl
from tests.factories import make_boundary

VARIANT = Variant.parse("prod-plain:fake:head4k")
ARM = Arm(
    key="fake",
    model_id="vendor/fake",
    endpoint="test",
    base_url="http://test",
    provider="p",
    temperature=0.0,
    max_tokens=4096,
    reasoning="provider-default",
)


class FakeJudge:
    def __init__(
        self,
        reply='{"verdict": "done", "reason": "looks done"}',
        fail_on=(),
        model="fake-0001",
        switch_after=None,
    ):
        self.reply = reply
        self.fail_on = set(fail_on)
        self.model = model
        self.switch_after = switch_after
        self.calls = 0
        self._lock = threading.Lock()

    def __call__(self, messages):
        with self._lock:
            self.calls += 1
            n = self.calls
        if any(f in messages[1]["content"] for f in self.fail_on):
            attempts = (Attempt(1, False, "RateLimitError", 429, True),) * 2
            raise TransportError("429", attempts)
        model = self.model if self.switch_after is None or n <= self.switch_after else "fake-0002"
        return CompletionResult(
            text=self.reply,
            model_reported=model,
            provider_reported="Prov",
            finish_reason="stop",
            tokens_in=10,
            cost_usd=0.001,
            attempts=(Attempt(1, True),),
        )


def _boundaries(n=3):
    return [make_boundary(boundary_id=f"t/b{i}", last_response=f"Response {i}.") for i in range(n)]


def _run(tmp_path, boundaries, fake, samples=2, workers=4):
    return replay(
        boundaries,
        [VARIANT],
        samples=samples,
        run_dir=tmp_path,
        arms={"fake": ARM},
        completions={"fake": fake},
        workers=workers,
    )


def _verdicts(tmp_path):
    return list(read_jsonl(verdict_path(tmp_path, VARIANT), JudgeVerdict))


def test_writes_one_verdict_per_boundary_and_sample(tmp_path):
    fake = FakeJudge()
    counts = _run(tmp_path, _boundaries(), fake)
    recs = _verdicts(tmp_path)
    assert counts["parsed"] == 6 and fake.calls == 6
    assert {(r.boundary_id, r.sample) for r in recs} == {
        (f"t/b{i}", s) for i in range(3) for s in range(2)
    }
    assert {r.arm_id for r in recs} == {ARM.arm_id}
    assert len({r.sub_arm_id for r in recs}) == 1
    assert all(r.raw and r.finish_reason == "stop" and r.cost_usd == 0.001 for r in recs)


def test_rerun_skips_finished_samples(tmp_path):
    _run(tmp_path, _boundaries(), FakeJudge())
    fake = FakeJudge()
    counts = _run(tmp_path, _boundaries(4), fake, samples=3)
    assert fake.calls == 4 * 3 - 6
    assert counts["skipped"] == 6


def test_transport_failure_logs_attempts_and_never_becomes_a_verdict(tmp_path):
    counts = _run(tmp_path, _boundaries(), FakeJudge(fail_on={"Response 1."}))
    assert counts["transport_failed"] == 2
    assert "t/b1" not in {r.boundary_id for r in _verdicts(tmp_path)}
    attempts = list(read_jsonl(tmp_path / "attempts.jsonl", AttemptRecord))
    failed = [a for a in attempts if a.status == "error"]
    assert {a.boundary_id for a in failed} == {"t/b1"}
    assert all(a.http_status == 429 and a.retryable for a in failed)

    fake = FakeJudge()
    _run(tmp_path, _boundaries(), fake)
    assert fake.calls == 2


def test_empty_response_short_circuits_like_production(tmp_path):
    fake = FakeJudge()
    _run(tmp_path, [make_boundary(boundary_id="t/empty", last_response="  \n")], fake, samples=1)
    (rec,) = _verdicts(tmp_path)
    assert fake.calls == 0
    assert (rec.outcome, rec.verdict, rec.reason) == ("no_call", "continue", EMPTY_RESPONSE_REASON)


def test_outcomes_are_classified(tmp_path):
    counts = _run(tmp_path, _boundaries(1), FakeJudge(reply="I think it is done."), samples=1)
    (rec,) = _verdicts(tmp_path)
    assert counts["parse_failed"] == 1
    assert rec.outcome == "parse_failed" and rec.decision == "continue"
    assert rec.raw == "I think it is done."


def test_format_violation_recorded(tmp_path):
    _run(tmp_path, _boundaries(1), FakeJudge(reply='{"verdict": "finished"}'), samples=1)
    (rec,) = _verdicts(tmp_path)
    assert (rec.outcome, rec.format_violation, rec.decision) == (
        "format_violation",
        "unknown_label",
        "continue",
    )


def test_identity_change_halts_arm_and_splits_sub_arms(tmp_path):
    fake = FakeJudge(switch_after=3)
    counts = _run(tmp_path, _boundaries(10), fake, samples=1, workers=1)
    recs = load_verdicts(tmp_path)
    assert counts["drift_incidents"] == 1
    assert counts["halted"] == 10 - 4
    assert fake.calls == 4  # the call that revealed the change is kept, nothing after it runs
    subs = {r.sub_arm_id for r in recs}
    assert len(subs) == 2
    (incident,) = read_jsonl(tmp_path / "incidents.jsonl", DriftIncident)
    assert incident.expected["model"] == "fake-0001"
    assert incident.observed["model"] == "fake-0002"

    # A halted arm stays halted for the rest of the run.
    again = FakeJudge()
    counts = _run(tmp_path, _boundaries(10), again, samples=1, workers=1)
    assert again.calls == 0 and counts["halted"] == 6


def test_identity_baseline_survives_resume(tmp_path):
    _run(tmp_path, _boundaries(2), FakeJudge(), samples=1)
    counts = _run(tmp_path, _boundaries(4), FakeJudge(model="fake-0009"), samples=1, workers=1)
    assert counts["drift_incidents"] == 1
    lines = (tmp_path / "incidents.jsonl").read_text().splitlines()
    assert json.loads(lines[0])["expected"]["model"] == "fake-0001"


def test_reparse_rewrites_copies_only(tmp_path):
    from hjr.replay import reparse

    _run(tmp_path, _boundaries(1), FakeJudge(reply='{"verdict": "finished"}'), samples=1)
    original = (verdict_path(tmp_path, VARIANT)).read_text()
    counts = reparse(tmp_path, tmp_path / "reparsed")
    assert counts["records"] == 1 and counts["outcome_changed"] == 0
    assert verdict_path(tmp_path, VARIANT).read_text() == original
    (rec,) = read_jsonl(
        tmp_path / "reparsed" / "judge" / verdict_path(tmp_path, VARIANT).name, JudgeVerdict
    )
    assert rec.format_violation == "unknown_label"


def test_repair_prompt_refused_on_heldout_before_the_freeze(tmp_path, monkeypatch):
    monkeypatch.setattr("hjr.pools.judge_unsealed", lambda *a, **k: False)
    repair = Variant.parse("repair-v1:fake:evidence")
    heldout = [make_boundary(boundary_id="t/h0", split="heldout")]
    fake = FakeJudge()
    with pytest.raises(PermissionError, match="repair-freeze-v1"):
        replay(
            heldout,
            [repair],
            samples=1,
            run_dir=tmp_path,
            arms={"fake": ARM},
            completions={"fake": fake},
        )
    assert fake.calls == 0
    # Dev boundaries, and the production prompt on held-out ones, are not affected.
    replay(
        _boundaries(1),
        [repair],
        samples=1,
        run_dir=tmp_path,
        arms={"fake": ARM},
        completions={"fake": fake},
    )
    _run(tmp_path, heldout, fake, samples=1)
    assert fake.calls == 2


def test_repair_prompt_allowed_on_heldout_after_the_freeze(tmp_path, monkeypatch):
    monkeypatch.setattr("hjr.pools.judge_unsealed", lambda *a, **k: True)
    fake = FakeJudge()
    replay(
        [make_boundary(boundary_id="t/h0", split="heldout")],
        [Variant.parse("repair-v1:fake:evidence")],
        samples=1,
        run_dir=tmp_path,
        arms={"fake": ARM},
        completions={"fake": fake},
    )
    assert fake.calls == 1


RUN = "phase2-sanity-weak"
RUN_ARGV = [
    "replay",
    "--boundaries",
    "data/frozen/phase1-weak.jsonl",
    "--run-id",
    RUN,
    "--variant",
    "prod-plain:strong-api:head4k",
    "--subset",
    "sanity",
    "--workers",
    "1",
]


@pytest.fixture
def finished_run(tmp_path, monkeypatch):
    """A copy of a committed finished run; any model call it makes is answered by ``reply``."""
    import shutil

    from hjr import cli
    from hjr.config import ROOT

    runs = tmp_path / "runs"
    shutil.copytree(ROOT / "results" / "runs" / RUN, runs / RUN)
    monkeypatch.setattr(cli, "RUNS", runs)
    calls = []

    class StubClient:
        reply: dict | None = None

        def __init__(self, arm, **kwargs):
            pass

        def complete(self, messages):
            calls.append(messages)
            r = StubClient.reply
            if r is None:
                raise AssertionError("a finished run must make no model call")
            return CompletionResult(
                text=r["raw"],
                model_reported=r["judge_model_reported"],
                provider_reported=r["provider_reported"],
                finish_reason="stop",
                attempts=(Attempt(1, True),),
            )

    monkeypatch.setattr("hjr.client.JudgeClient", StubClient)
    return runs / RUN, StubClient, calls


def test_replay_of_finished_run_leaves_manifest_untouched(finished_run):
    from hjr import cli

    run_dir, _, calls = finished_run
    before = (run_dir / "manifest.json").read_bytes()
    assert cli.main(RUN_ARGV) == 0
    assert calls == []
    assert (run_dir / "manifest.json").read_bytes() == before


def test_replay_that_judges_something_rewrites_manifest(finished_run):
    from hjr import cli

    run_dir, stub, calls = finished_run
    path = run_dir / "judge" / "prod-plain__strong-api__head4k.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    path.write_text("".join(lines[:-1]), encoding="utf-8", newline="")
    stub.reply = json.loads(lines[-1])
    before = (run_dir / "manifest.json").read_bytes()
    assert cli.main(RUN_ARGV) == 0
    assert len(calls) == 1
    assert (run_dir / "manifest.json").read_bytes() != before
