from __future__ import annotations

import json
import threading

from hjr.config import load_judge_config
from hjr.judge import CompletionResult, Variant
from hjr.replay import EMPTY_RESPONSE_REASON, replay, verdict_path
from hjr.schemas import JudgeVerdict, read_jsonl
from tests.factories import make_boundary

VARIANT = Variant.parse("prod-plain:fake:head4k")


class FakeJudge:
    def __init__(self, reply='{"verdict": "done", "reason": "looks done"}', fail_on=()):
        self.reply = reply
        self.fail_on = set(fail_on)
        self.calls = 0
        self._lock = threading.Lock()

    def __call__(self, messages):
        with self._lock:
            self.calls += 1
        if any(f in messages[1]["content"] for f in self.fail_on):
            raise ConnectionError("provider down")
        return CompletionResult(text=self.reply, model_reported="fake-0001", tokens_in=10)


def _boundaries(n=3):
    return [make_boundary(boundary_id=f"t/b{i}", last_response=f"Response {i}.") for i in range(n)]


def _run(tmp_path, boundaries, fake, samples=2):
    return replay(
        boundaries,
        [VARIANT],
        samples=samples,
        run_dir=tmp_path,
        completions={"fake": fake},
        model_ids={"fake": "vendor/fake"},
        workers=4,
    )


def test_writes_one_verdict_per_boundary_and_sample(tmp_path):
    fake = FakeJudge()
    counts = _run(tmp_path, _boundaries(), fake)
    recs = list(read_jsonl(verdict_path(tmp_path, VARIANT), JudgeVerdict))
    assert counts["ok"] == 6 and fake.calls == 6
    assert {(r.boundary_id, r.sample) for r in recs} == {
        (f"t/b{i}", s) for i in range(3) for s in range(2)
    }
    assert all(r.decision == "done" and r.judge_model_reported == "fake-0001" for r in recs)


def test_rerun_skips_finished_samples(tmp_path):
    _run(tmp_path, _boundaries(), FakeJudge())
    fake = FakeJudge()
    counts = _run(tmp_path, _boundaries(4), fake, samples=3)
    assert fake.calls == 4 * 3 - 6
    assert counts["skipped"] == 6


def test_failures_are_logged_and_retried_next_run(tmp_path):
    counts = _run(tmp_path, _boundaries(), FakeJudge(fail_on={"Response 1."}))
    assert counts["failed"] == 2
    errors = [json.loads(x) for x in (tmp_path / "errors.jsonl").read_text().splitlines()]
    assert {e["boundary_id"] for e in errors} == {"t/b1"}

    fake = FakeJudge()
    _run(tmp_path, _boundaries(), fake)
    assert fake.calls == 2


def test_empty_response_short_circuits_like_production(tmp_path):
    fake = FakeJudge()
    _run(tmp_path, [make_boundary(boundary_id="t/empty", last_response="  \n")], fake, samples=1)
    (rec,) = read_jsonl(verdict_path(tmp_path, VARIANT), JudgeVerdict)
    assert fake.calls == 0
    assert (rec.verdict, rec.reason) == ("continue", EMPTY_RESPONSE_REASON)


def test_unparseable_reply_counts_as_parse_failure(tmp_path):
    counts = _run(tmp_path, _boundaries(1), FakeJudge(reply="I think it is done."), samples=1)
    (rec,) = read_jsonl(verdict_path(tmp_path, VARIANT), JudgeVerdict)
    assert counts["parse_failed"] == 1
    assert rec.parse_failed and rec.decision == "continue"


def test_repo_judge_config_loads():
    cfg = load_judge_config()
    assert {"flash", "self-weak"} <= set(cfg.models)
    for model in cfg.models.values():
        assert model.provider, f"{model.key} must pin a provider"
