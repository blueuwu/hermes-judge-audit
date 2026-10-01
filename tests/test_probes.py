from __future__ import annotations

from collections import Counter

import pytest

from hjr import judge, metrics
from hjr.pilot import probes
from hjr.schemas import BoundaryRecord, read_jsonl

RECORDS = list(probes.build())


def test_probe_set_covers_every_shape_and_verdict():
    assert 18 <= len(RECORDS) <= 24
    assert {r.split for r in RECORDS} == {"probe"}
    expected = Counter(r.tags["expected"] for r in RECORDS)
    assert set(expected) == {"done", "continue", "blocked", "wait"}
    assert {"wait", "json-in-response", "resumed", "long-rationale"} <= {
        r.tags["shape"] for r in RECORDS
    }


def test_wait_probes_render_background_context():
    for r in RECORDS:
        user = judge.build_messages(r, prompt="prod-plain", view="head4k")[1]["content"]
        if r.background_processes:
            assert "Background processes the agent currently has running" in user
        if r.active_delegations:
            assert "Active delegations" in user


def test_probes_never_enter_accuracy_metrics():
    with pytest.raises(ValueError):
        metrics.truth_map(RECORDS)


def test_probe_ids_disjoint_from_pilot():
    from hjr.pilot import build

    assert not {r.boundary_id for r in RECORDS} & {r.boundary_id for r in build.build()}


def test_committed_file_matches_builder():
    assert list(read_jsonl(probes.OUTPUT, BoundaryRecord)) == RECORDS
