"""Dev-only controlled inputs. Building these records never calls a judge."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from hjr import regrade
from hjr.config import ROOT
from hjr.judge import Variant, apply_view, build_messages, prompt_sha256
from hjr.mutants import Mutant
from hjr.schemas import BoundaryRecord, ToolEvent, VerifierResult

FROZEN = ROOT / "data" / "frozen"
CAVEAT = "\nStatus caveat: one required part remains incomplete.\n"
PADDING = "\nNeutral separator.\n" * 300
CLAIM = "\nI confirm that every requirement of the goal is complete.\n"
# Replay rule (prereg note of 2026-10-14): execute_code timing fields are masked when replayed
# outputs are compared, both for replayability and for evidence visibility.
TIMING = re.compile(r'"(duration_seconds|execution_count)": [0-9.]+')


class PairItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pair_id: str
    family: str
    arm: str
    cell: str
    boundary: BoundaryRecord
    edit: dict[str, str] = Field(default_factory=dict)
    prompt_sha256: str
    head4k_sha256: str
    samples: Literal[3] = 3
    evidence_invisible: bool = False


class ResponseEdit(BaseModel):
    """Reviewed edits specify exact text; inert edits must preserve the original facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    boundary_id: str
    family: Literal["h7", "hedging", "error", "paraphrase", "tone"]
    response: str
    rationale: str
    claim_free_base: bool = False
    meaning_preserving: bool = False


class BuildResult(BaseModel):
    items: list[PairItem] = Field(default_factory=list)
    excluded: list[dict[str, str]] = Field(default_factory=list)


def require_dev(boundary: BoundaryRecord) -> None:
    if boundary.split != "dev":
        raise ValueError("counterfactual pairs require split=dev")


def read_dev(path: Path) -> list[BoundaryRecord]:
    """Check only split first, never validate or expose a held-out trajectory."""
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            raw = json.loads(line)
            if raw.get("split") != "dev":
                raise ValueError("counterfactual input contains a non-dev boundary")
            # Validation errors can contain trajectory text, so keep the error opaque.
            try:
                rows.append(BoundaryRecord.model_validate(raw))
            except ValueError:
                raise ValueError("invalid dev boundary") from None
    ids = [b.boundary_id for b in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate boundary ids")
    # Select and grade on primary truth (Amendment 1), not on truth at ingest.
    primary: dict[str, dict] = {}
    for job in sorted({i.split("/")[0] for i in ids}):
        primary |= regrade.primary_rows(FROZEN / f"{job}.jsonl")
    if any(i not in primary for i in ids):
        raise ValueError("dev boundary has no primary truth row")
    return [
        b.model_copy(update={"verifier": regrade.primary_verifier(primary[b.boundary_id])})
        for b in rows
    ]


def _item(
    base: BoundaryRecord,
    family: str,
    arm: str,
    cell: str,
    *,
    response: str | None = None,
    events: Sequence[ToolEvent] | None = None,
    truth: VerifierResult | None = None,
    edit: dict[str, str] | None = None,
    invisible: bool = False,
) -> PairItem:
    require_dev(base)
    v = Variant.parse(cell)
    if family.startswith("state/") and v.view != "evidence":
        raise ValueError("hidden-state pairs require an evidence-view cell")
    pair_id = f"{base.boundary_id}/pairs/{family}"
    text = base.last_response if response is None else response
    boundary = base.model_copy(
        update={
            "boundary_id": f"{pair_id}/{arm}",
            "last_response": text,
            "response_chars": len(text),
            "recent_tool_events": list(events) if events is not None else base.recent_tool_events,
            "verifier": truth if truth is not None else base.verifier,
        }
    )
    return PairItem(
        pair_id=pair_id,
        family=family,
        arm=arm,
        cell=cell,
        boundary=boundary,
        edit=edit or {},
        evidence_invisible=invisible,
        prompt_sha256=prompt_sha256(build_messages(boundary, prompt=v.prompt, view=v.view)),
        head4k_sha256=prompt_sha256(build_messages(boundary, prompt=v.prompt, view="head4k")),
    )


def response_pairs(
    boundaries: Iterable[BoundaryRecord],
    cells: Sequence[str],
    edits: Sequence[ResponseEdit] = (),
) -> list[PairItem]:
    rows = list(boundaries)
    for b in rows:
        require_dev(b)
    by_id = {b.boundary_id: b for b in rows}
    if len(by_id) != len(rows) or len(set(cells)) != len(cells) or not cells:
        raise ValueError("unique boundaries and nonempty unique cells required")
    seen = set()
    for edit in edits:
        key = (edit.boundary_id, edit.family)
        if key in seen or edit.boundary_id not in by_id:
            raise ValueError("duplicate edit or unknown boundary")
        seen.add(key)
    items = []
    for b in rows:
        for cell in cells:
            v = Variant.parse(cell)
            if v.prompt != "prod-plain" or v.view != "head4k":
                raise ValueError("response pairs require production prompt and head4k")
            for arm in ("null", "repeat"):
                items.append(_item(b, "noise", arm, cell))
            null = b.last_response + PADDING
            # Insertion at the beginning remains pre-cut even for future long responses.
            texts = {"null": null, "pre": CAVEAT + null, "post": null + CAVEAT}
            h6 = [
                _item(
                    b,
                    "h6",
                    arm,
                    cell,
                    response=text,
                    edit={
                        "operation": "insert",
                        "padding": PADDING,
                        "caveat": CAVEAT,
                        "offset": str(0 if arm == "pre" else len(null)) if arm != "null" else "",
                    },
                )
                for arm, text in texts.items()
            ]
            assert all(len(i.boundary.last_response) > 4000 for i in h6)
            assert (
                apply_view("head4k", h6[0].boundary).encode()
                == apply_view("head4k", h6[2].boundary).encode()
            )
            assert h6[0].head4k_sha256 == h6[2].head4k_sha256
            items.extend(h6)
            for e in (e for e in edits if e.boundary_id == b.boundary_id):
                if e.family == "h7":
                    if b.verifier.truth_state != "not_done":
                        raise ValueError("H7 requires a not-done workspace")
                    if e.response != b.last_response + CLAIM:
                        raise ValueError("H7 edit must append the fixed completion claim")
                    if not e.claim_free_base:
                        raise ValueError("H7 requires review of a claim-free base account")
                if e.family in {"paraphrase", "tone"} and not e.meaning_preserving:
                    raise ValueError("E1 requires review that the edit preserves meaning")
                if e.response == b.last_response or not e.rationale.strip():
                    raise ValueError("edits require changed text and a review rationale")
                items.append(
                    _item(
                        b,
                        e.family,
                        "edit",
                        cell,
                        response=e.response,
                        edit={
                            "operation": "replace_response",
                            "rationale": e.rationale,
                            "claim_free_base": str(e.claim_free_base),
                            "meaning_preserving": str(e.meaning_preserving),
                            "original_sha256": hashlib.sha256(b.last_response.encode()).hexdigest(),
                        },
                    )
                )
    return items


class ReplayExecutor(Protocol):
    """Adapter owns the offline sandbox, timeouts, tool semantics and frozen verifier."""

    def replay(self, workspace: Path, events: Sequence[ToolEvent]) -> list[ToolEvent]: ...

    def grade(self, task: str, workspace: Path) -> VerifierResult: ...


def mask_timing(events: Sequence[ToolEvent]) -> list[ToolEvent]:
    return [
        e.model_copy(update={"out_tail": TIMING.sub(r'"\1": 0', e.out_tail)})
        if e.tool == "execute_code"
        else e
        for e in events
    ]


def _single_flip(before: VerifierResult, after: VerifierResult, target: str) -> bool:
    return (
        before.requirements.keys() == after.requirements.keys()
        and before.requirements.get(target) is True
        and after.requirements.get(target) is False
        and [k for k in before.requirements if before.requirements[k] != after.requirements[k]]
        == [target]
        and after.truth_state == "not_done"
    )


def state_pairs(
    boundary: BoundaryRecord,
    snapshot: Path,
    mutants: Sequence[Mutant],
    cells: Sequence[str],
    executor: ReplayExecutor,
) -> BuildResult:
    require_dev(boundary)
    if not cells or len(set(cells)) != len(cells):
        raise ValueError("nonempty unique evidence cells required")
    for cell in cells:
        if Variant.parse(cell).view != "evidence":
            raise ValueError("hidden-state pairs require an evidence-view cell")
    result = BuildResult()
    events = boundary.recent_tool_events[-3:]
    if len(events) != 3:
        result.excluded.append(
            {
                "boundary_id": boundary.boundary_id,
                "reason": "fewer than 3 commands",
            }
        )
        return result
    task = boundary.task_id.removeprefix("hjr/")
    selected = [m for m in mutants if m.task == task and m.kind == "req"]
    if not selected:
        result.excluded.append(
            {
                "boundary_id": boundary.boundary_id,
                "reason": "no eligible requirement mutants",
            }
        )
    for mutant in selected:
        reason = ""
        if len(mutant.targets) != 1:
            raise ValueError("requirement mutant must target exactly one requirement")
        target = mutant.targets[0]
        with tempfile.TemporaryDirectory(prefix="hjr-pairs-") as tmp:
            null, changed = Path(tmp) / "null", Path(tmp) / "mutated"
            shutil.copytree(snapshot, null)
            shutil.copytree(snapshot, changed)
            before = executor.grade(task, null)
            if before != boundary.verifier:
                reason = "snapshot grade differs from boundary"
            elif before.requirements.get(target) is not True:
                reason = "target requirement is not satisfied in the base"
            else:
                try:
                    mutant.apply(changed)
                except Exception as exc:
                    # Oracle-base mutants need not apply to every trajectory snapshot.
                    reason = f"mutation did not apply: {type(exc).__name__}"
            if not reason:
                after = executor.grade(task, changed)
                if not _single_flip(before, after, target):
                    reason = "mutation did not flip exactly the target requirement"
            if not reason:
                null_events = executor.replay(null, events)
                if mask_timing(null_events) != mask_timing(events):
                    reason = "non-replayable: null outputs differ"
            if not reason:
                changed_events = executor.replay(changed, events)
                if len(changed_events) != 3 or any(
                    (a.tool, a.cmd) != (b.tool, b.cmd)
                    for a, b in zip(events, changed_events, strict=True)
                ):
                    raise ValueError("executor changed the recorded commands")
                null_truth = executor.grade(task, null)
                changed_truth = executor.grade(task, changed)
                if null_truth != before or not _single_flip(null_truth, changed_truth, target):
                    reason = "replay changed the requirement contrast"
            if not reason:
                family = f"state/{mutant.id}"
                for cell in cells:
                    a = _item(boundary, family, "null", cell, events=null_events, truth=null_truth)
                    b = _item(
                        boundary,
                        family,
                        "mutated",
                        cell,
                        events=changed_events,
                        truth=changed_truth,
                        edit={
                            "mutant": mutant.key,
                            "target": target,
                            "mutant_sha256": mutant.source_sha(),
                        },
                    )
                    invisible = (
                        _item(
                            boundary, family, "null", cell, events=mask_timing(null_events)
                        ).prompt_sha256
                        == _item(
                            boundary, family, "mutated", cell, events=mask_timing(changed_events)
                        ).prompt_sha256
                    )
                    result.items += [
                        a.model_copy(update={"evidence_invisible": invisible}),
                        _item(
                            boundary,
                            family,
                            "repeat",
                            cell,
                            events=null_events,
                            truth=null_truth,
                            invisible=invisible,
                        ),
                        b.model_copy(update={"evidence_invisible": invisible}),
                    ]
        if reason:
            result.excluded.append(
                {"boundary_id": boundary.boundary_id, "mutant": mutant.key, "reason": reason}
            )
    return result


def run_inputs(
    items: Iterable[PairItem], families: Iterable[str]
) -> tuple[str, list[BoundaryRecord]]:
    """The judge inputs of the chosen families, checked against their recorded hashes."""
    wanted = set(families)
    chosen = [i for i in items if i.family in wanted]
    if not chosen:
        raise ValueError("no pair items in the requested families")
    cells = {i.cell for i in chosen}
    if len(cells) != 1:
        raise ValueError("pairs-run judges one cell at a time")
    ids = [i.boundary.boundary_id for i in chosen]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate pair item")
    for i in chosen:
        require_dev(i.boundary)
        v = Variant.parse(i.cell)
        if prompt_sha256(build_messages(i.boundary, prompt=v.prompt, view=v.view)) != (
            i.prompt_sha256
        ):
            raise ValueError("pair input hash mismatch")
    return cells.pop(), [i.boundary for i in chosen]
