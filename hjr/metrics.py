"""Judge reliability and accuracy, kept separate.

Reliability comes first: transport errors (from attempts), parse failures and format
violations. Accuracy is then scored three ways over the calls that returned a response:

* semantic (primary): only parsed calls with a recognised verdict; the denominator is shown.
* effective: what Hermes production does. Parse failures and format violations count as the
  CONTINUE that Hermes falls back to. Fail-open pushes errors toward CONTINUE, which lowers
  false-DONE artificially, so effective false-DONE flatters an unreliable judge.
* strict (sensitivity): parse failures and format violations count as wrong.

``no_call`` records (Hermes skips the judge on an empty response) carry the production verdict
in effective and strict scoring and are excluded from semantic scoring and from format rates.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from hjr.arms import MixedArmError, require_single_arm
from hjr.schemas import AttemptRecord, BoundaryRecord, JudgeVerdict

EXPECTED_DECISION = {"done": "done", "not_done": "continue", "blocked": "blocked"}


@dataclass(frozen=True)
class Rate:
    k: int
    n: int

    @property
    def value(self) -> float | None:
        return self.k / self.n if self.n else None

    def __str__(self) -> str:
        if not self.n:
            return "–"
        return f"{self.k}/{self.n} ({100 * self.k / self.n:.1f}%)"


@dataclass(frozen=True)
class JudgeScores:
    model_calls: int
    parse_failures: Rate
    format_violations: Rate
    semantic_accuracy: Rate
    effective_accuracy: Rate
    strict_accuracy: Rate
    # Per truth class, under effective scoring (what production would have done)
    false_done_effective: Rate
    false_continue_effective: Rate
    # Same rates restricted to parsed, recognised verdicts
    false_done_semantic: Rate
    false_continue_semantic: Rate


def truth_map(boundaries: Iterable[BoundaryRecord]) -> dict[str, str]:
    out = {}
    for b in boundaries:
        if b.split == "probe":
            raise ValueError(f"{b.boundary_id} is a format probe and cannot enter accuracy metrics")
        out[b.boundary_id] = b.verifier.truth_state
    return out


def check_poolable(verdicts: list[JudgeVerdict], *, what: str) -> None:
    """One arm, one sub-arm. ``no_call`` records have no sub-arm and only need the arm."""
    called = [v for v in verdicts if v.outcome != "no_call"]
    if called:
        arm_id, _ = require_single_arm(called, what=what)
    else:
        arm_id = verdicts[0].arm_id if verdicts else ""
    if any(v.arm_id != arm_id for v in verdicts):
        raise MixedArmError(f"refusing to pool {what} across arms")
    if len({v.variant for v in verdicts}) > 1:
        raise MixedArmError(f"refusing to pool {what} across judge variants")


def score(verdicts: list[JudgeVerdict], truth: Mapping[str, str], *, what: str) -> JudgeScores:
    check_poolable(verdicts, what=what)
    missing = {v.boundary_id for v in verdicts} - truth.keys()
    if missing:
        raise KeyError(f"no truth for {len(missing)} boundaries, e.g. {sorted(missing)[0]}")

    called = [v for v in verdicts if v.outcome != "no_call"]
    parsed = [v for v in called if v.outcome == "parsed"]

    def correct(v: JudgeVerdict) -> bool:
        return v.decision == EXPECTED_DECISION[truth[v.boundary_id]]

    def strict_correct(v: JudgeVerdict) -> bool:
        return v.outcome in ("parsed", "no_call") and correct(v)

    def false_done(rows: list[JudgeVerdict]) -> Rate:
        neg = [v for v in rows if truth[v.boundary_id] != "done"]
        return Rate(sum(v.decision == "done" for v in neg), len(neg))

    def false_continue(rows: list[JudgeVerdict]) -> Rate:
        pos = [v for v in rows if truth[v.boundary_id] == "done"]
        return Rate(sum(v.decision != "done" for v in pos), len(pos))

    return JudgeScores(
        model_calls=len(called),
        parse_failures=Rate(sum(v.outcome == "parse_failed" for v in called), len(called)),
        format_violations=Rate(sum(v.outcome == "format_violation" for v in called), len(called)),
        semantic_accuracy=Rate(sum(map(correct, parsed)), len(parsed)),
        effective_accuracy=Rate(sum(map(correct, verdicts)), len(verdicts)),
        strict_accuracy=Rate(sum(map(strict_correct, verdicts)), len(verdicts)),
        false_done_effective=false_done(verdicts),
        false_continue_effective=false_continue(verdicts),
        false_done_semantic=false_done(parsed),
        false_continue_semantic=false_continue(parsed),
    )


@dataclass(frozen=True)
class TransportStats:
    attempts: int
    errors: int
    retryable_errors: int
    by_type: dict[str, int]
    # Calls whose attempts all failed and that have no verdict yet
    unresolved_calls: int

    @property
    def error_rate(self) -> Rate:
        return Rate(self.errors, self.attempts)


def transport_stats(
    attempts: Iterable[AttemptRecord], verdicts: Iterable[JudgeVerdict], *, variant: str
) -> TransportStats:
    rows = [a for a in attempts if a.variant == variant]
    answered = {(v.boundary_id, v.sample) for v in verdicts if v.variant == variant}
    tried = {(a.boundary_id, a.sample) for a in rows}
    by_type: dict[str, int] = defaultdict(int)
    for a in rows:
        if a.status == "error":
            by_type[a.error_type or f"HTTP {a.http_status}"] += 1
    return TransportStats(
        attempts=len(rows),
        errors=sum(a.status == "error" for a in rows),
        retryable_errors=sum(a.status == "error" and a.retryable for a in rows),
        by_type=dict(by_type),
        unresolved_calls=len(tried - answered),
    )


def group_by_variant(
    verdicts: Iterable[JudgeVerdict], *, split_sub_arms: bool = False
) -> dict[str, list[JudgeVerdict]]:
    """Group for reporting. Mixed sub-arms within a variant raise unless split explicitly."""
    groups: dict[str, list[JudgeVerdict]] = defaultdict(list)
    for v in verdicts:
        groups[v.variant].append(v)
    if not split_sub_arms:
        for name, rows in groups.items():
            check_poolable(rows, what=f"variant {name}")
        return dict(groups)
    split: dict[str, list[JudgeVerdict]] = defaultdict(list)
    for name, rows in groups.items():
        subs = {v.sub_arm_id for v in rows if v.sub_arm_id}
        for v in rows:
            label = name if len(subs) <= 1 else f"{name} [sub-arm {v.sub_arm_id or 'none'}]"
            split[label].append(v)
    return dict(split)
