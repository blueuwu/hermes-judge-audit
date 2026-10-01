from __future__ import annotations

from collections import Counter

import pytest

from hjr import judge
from hjr.pilot import build
from hjr.schemas import BoundaryRecord, read_jsonl

RECORDS = list(build.build())
TRUNC = [r for r in RECORDS if r.category == "TRUNC"]


def test_ids_unique_and_all_dev():
    assert len({r.boundary_id for r in RECORDS}) == len(RECORDS)
    assert {r.split for r in RECORDS} == {"dev"}
    assert {r.verifier.source for r in RECORDS} == {"constructed"}


def test_category_balance():
    counts = Counter(r.category for r in RECORDS)
    assert counts["TRUNC"] == 16 and counts["TRUNC-CTL"] == 4
    for cat in ("A1", "A4", "A6", "A7", "A8", "CTL-ND", "CTL-D"):
        assert counts[cat] == 4, cat


@pytest.mark.parametrize("rec", TRUNC, ids=lambda r: r.boundary_id)
def test_caveat_visibility_matches_design(rec):
    target = rec.tags["caveat_target"]
    caveat = rec.last_response[rec.tags["caveat_offset"] : rec.tags["caveat_end"]]
    head, headtail = build.EXPECTED_VISIBILITY[target]
    assert (caveat in judge.view_head4k(rec.last_response)) is head
    assert (caveat in judge.view_headtail4k(rec.last_response)) is headtail
    assert abs(rec.tags["caveat_offset"] - target) < 700


def test_controls_contain_no_caveat():
    for rec in RECORDS:
        if rec.category == "TRUNC-CTL":
            scenario = rec.tags["scenario"]
            caveats = {
                r.last_response[r.tags["caveat_offset"] : r.tags["caveat_end"]]
                for r in TRUNC
                if r.tags["scenario"] == scenario
            }
            assert all(c not in rec.last_response for c in caveats)


def test_committed_file_matches_builder():
    committed = list(read_jsonl(build.OUTPUT, BoundaryRecord))
    assert committed == RECORDS, "run `uv run hjr pilot-build` and commit the result"
