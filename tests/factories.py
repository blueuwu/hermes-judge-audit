from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from hjr.schemas import BoundaryRecord, VerifierResult


def make_boundary(**overrides: Any) -> BoundaryRecord:
    fields: dict[str, Any] = dict(
        boundary_id="test/b00",
        run_id="test",
        task_id="test/task",
        category="T",
        split="dev",
        goal="Write hello.txt containing 'hello'.",
        last_response="Wrote hello.txt.",
        verifier=VerifierResult(truth_state="done", source="constructed"),
        hermes_sha="ffc74885",
        ts=datetime(2026, 10, 5, 14, 2, 11, tzinfo=UTC),
    )
    fields.update(overrides)
    fields.setdefault("response_chars", len(fields["last_response"]))
    return BoundaryRecord(**fields)
