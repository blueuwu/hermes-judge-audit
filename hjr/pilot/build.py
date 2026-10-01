"""Assemble the M0.5 pilot boundaries into ``data/frozen/pilot_boundaries.jsonl``."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from hjr import judge
from hjr.config import ROOT
from hjr.pilot.items import ITEMS
from hjr.pilot.reports import CAVEAT_OFFSETS, SCENARIOS, Scenario, blocks
from hjr.schemas import BoundaryRecord, VerifierResult, write_jsonl

RUN_ID = "pilot-v1"
OUTPUT = ROOT / "data" / "frozen" / "pilot_boundaries.jsonl"
# Fixed so the judge prompt ("Current time: ...") and every hash are reproducible.
TIMESTAMP = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
HERMES_SHA = "ffc74885c5f6eb75f6c134fb4eef86d734066623"
SEP = "\n\n"

# target offset -> (visible to head4k, visible to headtail4k)
EXPECTED_VISIBILITY = {
    1000: (True, True),
    3500: (True, False),
    4500: (False, False),
    8000: (False, True),
}
assert set(EXPECTED_VISIBILITY) == set(CAVEAT_OFFSETS)


def _visibility(view_text: str, caveat: str) -> bool | None:
    """True if the whole caveat is visible, False if none of it is, None if it is split."""
    if caveat in view_text:
        return True
    if caveat[:40] in view_text or caveat[-40:] in view_text:
        return None
    return False


def place_caveat(s: Scenario, target: int) -> tuple[str, int]:
    """Insert the caveat at the block boundary nearest ``target`` that gives the expected
    visibility under both views. Returns the report and the caveat's character offset."""
    parts = blocks(s)
    want = EXPECTED_VISIBILITY[target]
    best: tuple[int, str, int] | None = None
    for k in range(1, len(parts) + 1):
        text = SEP.join([*parts[:k], s.caveat, *parts[k:]])
        offset = text.index(s.caveat)
        seen = (
            _visibility(judge.view_head4k(text), s.caveat),
            _visibility(judge.view_headtail4k(text), s.caveat),
        )
        if seen != want:
            continue
        distance = abs(offset - target)
        if best is None or distance < best[0]:
            best = (distance, text, offset)
    if best is None:
        raise ValueError(f"{s.key}: no block boundary gives visibility {want} near {target}")
    return best[1], best[2]


def _record(
    key: str, category: str, goal: str, response: str, truth: str, **tags
) -> BoundaryRecord:
    requirements = tags.pop("requirements", None) or {}
    return BoundaryRecord(
        boundary_id=f"{RUN_ID}/{key}",
        run_id=RUN_ID,
        task_id=f"pilot/{key}",
        category=category,
        split="dev",
        goal=goal,
        last_response=response,
        response_chars=len(response),
        verifier=VerifierResult(truth_state=truth, requirements=requirements, source="constructed"),
        tags={k: v for k, v in tags.items() if v not in (None, "")},
        hermes_sha=HERMES_SHA,
        ts=TIMESTAMP,
    )


def build() -> Iterator[BoundaryRecord]:
    for item in ITEMS:
        yield _record(
            item.key,
            item.attack,
            item.goal,
            item.response,
            item.truth,
            note=item.note,
            requirements=item.requirements,
        )
    for s in SCENARIOS:
        clean = SEP.join(blocks(s))
        yield _record(f"trunc-{s.key}-none", "TRUNC-CTL", s.goal, clean, "done", scenario=s.key)
        for target in CAVEAT_OFFSETS:
            text, offset = place_caveat(s, target)
            yield _record(
                f"trunc-{s.key}-{target}",
                "TRUNC",
                s.goal,
                text,
                "not_done",
                scenario=s.key,
                caveat_target=target,
                caveat_offset=offset,
                caveat_end=offset + len(s.caveat),
            )


def write(path: Path = OUTPUT) -> int:
    return write_jsonl(path, build())
