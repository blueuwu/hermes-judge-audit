from __future__ import annotations

import pytest
from hermes_cli import goals as hg

from hjr import judge
from hjr.schemas import ToolEvent
from tests.factories import make_boundary

LIMIT = judge.RESPONSE_CHARS


@pytest.mark.parametrize("n", [0, 1, LIMIT - 1, LIMIT, LIMIT + 1, 3 * LIMIT])
def test_head4k_is_production_truncate(n):
    text = "a" * n
    assert judge.view_head4k(text) == hg._truncate(text, LIMIT)


@pytest.mark.parametrize("n", [0, 1, LIMIT])
def test_headtail4k_passes_short_text_through(n):
    text = "b" * n
    assert judge.view_headtail4k(text) == text


def test_headtail4k_keeps_both_ends():
    text = "HEAD" + "m" * 10_000 + "TAIL"
    out = judge.view_headtail4k(text)
    assert out.startswith("HEAD")
    assert out.endswith("TAIL")
    assert judge.HEADTAIL_MARKER in out
    assert len(out) == LIMIT + len(judge.HEADTAIL_MARKER)


def test_head4k_drops_a_late_caveat_that_headtail4k_keeps():
    caveat = "Two tests still fail."
    text = "All done. " + "detail " * 1000 + caveat
    assert caveat not in judge.view_head4k(text)
    assert caveat in judge.view_headtail4k(text)


def test_evidence_appends_last_three_tool_events():
    events = [
        ToolEvent(tool="terminal", cmd=f"step {i}", exit=i, out_tail=f"out {i}") for i in range(5)
    ]
    boundary = make_boundary(last_response="Done.", recent_tool_events=events)
    out = judge.apply_view("evidence", boundary)
    assert out.startswith("Done.")
    assert "step 1" not in out
    for i in (2, 3, 4):
        assert f"- terminal: step {i} → exit {i} | out {i}" in out


def test_evidence_without_events_equals_headtail():
    boundary = make_boundary(last_response="x" * 9000)
    assert judge.apply_view("evidence", boundary) == judge.view_headtail4k("x" * 9000)


def test_evidence_clips_long_tool_output_to_its_tail():
    out_tail = "noise\n" * 200 + "FATAL: permission denied"
    events = [ToolEvent(tool="terminal", cmd="cp a b", exit=1, out_tail=out_tail)]
    block = judge.render_tool_events(events)
    assert block.endswith("FATAL: permission denied")
    assert len(block) < judge.EVIDENCE_OUTPUT_CHARS + 50


def test_unknown_view_and_prompt_rejected():
    boundary = make_boundary()
    with pytest.raises(ValueError):
        judge.apply_view("tail4k", boundary)
    with pytest.raises(ValueError):
        judge.build_messages(boundary, prompt="repair-v9", view="head4k")


def test_prod_contract_requires_contract():
    with pytest.raises(ValueError):
        judge.build_messages(make_boundary(), prompt="prod-contract", view="head4k")


def test_prompt_hash_is_stable_and_sensitive():
    a = judge.build_messages(make_boundary(), prompt="prod-plain", view="head4k")
    b = judge.build_messages(
        make_boundary(goal="Something else."), prompt="prod-plain", view="head4k"
    )
    assert judge.prompt_sha256(a) == judge.prompt_sha256(list(a))
    assert judge.prompt_sha256(a) != judge.prompt_sha256(b)


@pytest.mark.parametrize(
    "spec",
    ["prod-plain:flash:head4k", "prod-contract:self-weak:evidence"],
)
def test_variant_round_trips(spec):
    assert str(judge.Variant.parse(spec)) == spec


@pytest.mark.parametrize(
    "spec", ["prod-plain:flash", "prod-x:flash:head4k", "prod-plain:flash:tail"]
)
def test_variant_rejects_bad_specs(spec):
    with pytest.raises(ValueError):
        judge.Variant.parse(spec)
