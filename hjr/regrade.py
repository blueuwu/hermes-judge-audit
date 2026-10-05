"""Regrade the frozen Phase 1a boundaries at the current verifier versions (primary truth).

Prereg Amendment 1: primary truth is the state verifier as frozen once the mutation suite
passes, and every frozen snapshot is regraded after a verifier bump, with the regrade logged.
Each boundary's own ``bNN.tgz`` (from its Phase 1 job, which is not committed) is graded in
its task's verifier image, exactly as ``hjr mutants`` grades.

Output, per arm: ``data/truth/<boundaries stem>.jsonl`` (one row per boundary: version, truth,
requirements, and the v1 truth frozen at ingest) and ``results/regrade/<stem>.md``, which lists
every boundary whose truth changed. Nothing is written if a snapshot is missing or fails to
grade, or if a task's ``tests/`` no longer matches its version in ``data/verifiers.json``.
A task still at v1 must reproduce its ingest truth exactly; a mismatch is reported and fails
the command, since it would mean grading is not deterministic.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from hjr import verifier
from hjr.config import ROOT
from hjr.manifest import git_state
from hjr.schemas import BoundaryRecord, VerifierResult, read_jsonl

JOBS = ROOT / "jobs"
TRUTH = ROOT / "data" / "truth"
LOG = ROOT / "results" / "regrade"


@dataclass(frozen=True)
class Row:
    boundary_id: str
    task: str
    split: str
    verifier_version: str
    tests_sha256: str
    truth_state: str
    requirements: dict[str, bool]
    v1_truth_state: str


def snapshot_path(boundary_id: str, jobs: Path = JOBS) -> Path:
    """'phase1-weak/<trial>/b01' -> jobs/phase1-weak/<trial>/artifacts/.../boundaries/b01.tgz"""
    job, trial, snap = boundary_id.split("/")
    return jobs / job / trial / "artifacts" / "logs" / "artifacts" / "boundaries" / f"{snap}.tgz"


def check_versions(tasks: set[str]) -> None:
    for task in sorted(tasks):
        version, sha = verifier.version_of(task)
        if verifier.tests_sha(task) != sha:
            raise SystemExit(f"{task}: tests/ does not match {version} in data/verifiers.json")


def regrade(boundaries: list[BoundaryRecord], jobs: Path = JOBS) -> list[Row]:
    by_task: dict[str, list[BoundaryRecord]] = defaultdict(list)
    for b in boundaries:
        by_task[verifier.task_name(b.task_id)].append(b)
    check_versions(set(by_task))
    missing = [
        b.boundary_id for b in boundaries if not snapshot_path(b.boundary_id, jobs).is_file()
    ]
    if missing:
        raise SystemExit(f"{len(missing)} snapshots missing, e.g. {missing[0]}")
    rows, failed = [], []
    for task, recs in sorted(by_task.items()):
        version, sha = verifier.version_of(task)
        snaps = [snapshot_path(b.boundary_id, jobs).read_bytes() for b in recs]
        for b, g in zip(recs, verifier.grade_snapshots(task, snaps), strict=True):
            if not g.ok:
                failed.append(f"{b.boundary_id}: {g.error[:300]}")
                continue
            rows.append(
                Row(
                    b.boundary_id,
                    task,
                    b.split,
                    version,
                    sha,
                    g.truth_state,
                    g.requirements,
                    b.verifier.truth_state,
                )
            )
    if failed:
        raise SystemExit("snapshots failed to grade:\n" + "\n".join(failed))
    return sorted(rows, key=lambda r: r.boundary_id)


def not_reproduced(rows: list[Row]) -> list[Row]:
    """v1 tasks whose regrade differs from the truth frozen at ingest."""
    return [r for r in rows if r.verifier_version == "v1" and r.truth_state != r.v1_truth_state]


def report(name: str, rows: list[Row], commit: str, dirty: bool) -> str:
    changed = [r for r in rows if r.truth_state != r.v1_truth_state]
    bad = not_reproduced(rows)
    versions = Counter(r.verifier_version for r in rows)
    lines = [
        f"# Regrade of `{name}`",
        "",
        f"Commit `{commit}`{' (dirty tree)' if dirty else ''}; {len(rows)} boundaries. "
        "Verifier versions: " + ", ".join(f"{v} {n}" for v, n in sorted(versions.items())) + ".",
        "",
        f"v1 boundaries not reproducing their ingest truth: {len(bad)}.",
        "",
        "| truth at ingest (v1) | primary | n |",
        "|---|---|---|",
    ]
    pairs = Counter((r.v1_truth_state, r.truth_state) for r in rows)
    lines += [f"| {a} | {b} | {n} |" for (a, b), n in sorted(pairs.items())]
    lines += ["", f"## Changed ({len(changed)})", ""]
    lines += [
        f"- `{r.boundary_id}` ({r.split}, {r.verifier_version}): {r.v1_truth_state} -> "
        f"{r.truth_state}"
        for r in changed
    ]
    return "\n".join(lines) + "\n"


def write(name: str, rows: list[Row], truth_dir: Path = TRUTH, log_dir: Path = LOG) -> Path:
    commit, dirty = git_state()
    truth_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    out = truth_dir / f"{name}.jsonl"
    text = "".join(json.dumps(asdict(r), sort_keys=True) + "\n" for r in rows)
    out.write_text(text, encoding="utf-8", newline="\n")
    md = report(name, rows, commit, dirty)
    (log_dir / f"{name}.md").write_text(md, encoding="utf-8", newline="\n")
    return out


def load_truth(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8") as fh:
        return {r["boundary_id"]: r["truth_state"] for r in map(json.loads, fh)}


def primary_rows(path: Path) -> dict[str, dict]:
    """Primary truth rows (``hjr regrade``) for a frozen boundaries file, by boundary id."""
    truth = TRUTH / f"{path.stem}.jsonl"
    if not truth.is_file():
        raise ValueError(f"{truth} is missing: run `hjr regrade {path}` first")
    with truth.open(encoding="utf-8") as fh:
        return {r["boundary_id"]: r for r in map(json.loads, fh)}


def primary_verifier(row: dict) -> VerifierResult:
    return VerifierResult(truth_state=row["truth_state"], requirements=row["requirements"])


def run(boundaries_path: Path, jobs: Path = JOBS) -> tuple[Path, list[Row]]:
    rows = regrade(list(read_jsonl(boundaries_path, BoundaryRecord)), jobs)
    return write(boundaries_path.stem, rows), not_reproduced(rows)
