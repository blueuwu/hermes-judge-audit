"""Provenance for a run: code, Hermes and lockfile versions plus input hashes."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from hjr.arms import Arm
from hjr.config import ROOT
from hjr.schemas import AttemptRecord, RunManifest, read_jsonl

HERMES_DIR = ROOT / "third_party" / "hermes-agent"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git(*args: str, cwd: Path = ROOT) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def git_state() -> tuple[str, bool]:
    sha = _git("rev-parse", "HEAD")
    dirty = bool(_git("status", "--porcelain", "--untracked-files=no", "--", ".", ":!results"))
    return sha, dirty


def hermes_sha() -> str:
    return _git("rev-parse", "HEAD", cwd=HERMES_DIR)


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def observed_identities(verdicts) -> dict[str, list[dict[str, str | int]]]:
    seen: Counter[tuple[str, str, str, str]] = Counter()
    for v in verdicts:
        if v.outcome != "no_call":
            seen[(v.arm_id, v.sub_arm_id, v.judge_model_reported, v.provider_reported)] += 1
    out: dict[str, list[dict[str, str | int]]] = defaultdict(list)
    for (arm, sub, model, provider), n in sorted(seen.items()):
        out[arm].append({"sub_arm_id": sub, "model": model, "provider": provider, "calls": n})
    return dict(out)


def usage_by_variant(verdicts) -> dict[str, dict[str, float]]:
    """Measured tokens and spend per variant; cost is what the provider billed."""
    out: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for v in verdicts:
        u = out[v.variant]
        u["calls"] += v.outcome != "no_call"
        u["tokens_in"] += v.tokens_in
        u["tokens_out"] += v.tokens_out
        u["reasoning_tokens"] += v.reasoning_tokens
        u["cost_usd"] += v.cost_usd or 0.0
        u["calls_without_cost"] += v.outcome != "no_call" and v.cost_usd is None
    return {k: dict(u) for k, u in out.items()}


def run_counts(run_dir: Path, verdicts) -> dict[str, int]:
    counts: Counter[str] = Counter(v.outcome for v in verdicts)
    attempts_path = run_dir / "attempts.jsonl"
    if attempts_path.exists():
        for a in read_jsonl(attempts_path, AttemptRecord):
            counts["attempts"] += 1
            counts["attempt_errors"] += a.status == "error"
    incidents = run_dir / "incidents.jsonl"
    if incidents.exists():
        counts["drift_incidents"] = sum(1 for line in incidents.open() if line.strip())
    return dict(counts)


def judge_run_manifest(
    run_dir: Path,
    *,
    git_sha: str,
    git_dirty: bool,
    boundaries_path: Path,
    n_boundaries: int,
    variants: list[str],
    samples: int,
    arms: Mapping[str, Arm],
    judge_config_sha256: str,
    seed: int,
    started_at: datetime,
) -> RunManifest:
    """Merge this invocation into the run's manifest; counts are recomputed from disk."""
    from hjr.replay import load_verdicts

    path = run_dir / "manifest.json"
    prev = None
    if path.exists():
        prev = RunManifest.model_validate_json(path.read_text(encoding="utf-8"))
    verdicts = load_verdicts(run_dir)
    inputs = {**(prev.inputs if prev else {}), rel(boundaries_path): sha256_file(boundaries_path)}
    models = {**(prev.models if prev else {}), **{k: a.describe() for k, a in arms.items()}}
    return RunManifest(
        run_id=run_dir.name,
        kind="judge-replay",
        git_sha=git_sha,
        git_dirty=git_dirty,
        hermes_sha=hermes_sha(),
        uv_lock_sha256=sha256_file(ROOT / "uv.lock"),
        inputs=inputs,
        variants=sorted(set(prev.variants if prev else []) | set(variants)),
        samples=max(samples, prev.samples if prev else 0),
        judge_config_sha256=judge_config_sha256,
        models=models,
        observed_identities=observed_identities(verdicts),
        seed=seed,
        started_at=min(started_at, prev.started_at) if prev else started_at,
        finished_at=datetime.now(UTC),
        counts={"boundaries": n_boundaries, **run_counts(run_dir, verdicts)},
        usage=usage_by_variant(verdicts),
    )


def tree_sha256(root: Path) -> str:
    """Hash of every file under ``root``, keyed by relative path."""
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        h.update(path.relative_to(root).as_posix().encode() + b"\0" + sha256_file(path).encode())
    return h.hexdigest()


def soak_manifest(job_dirs: list[Path], tasks_dir: Path, task_ids: list[str]) -> dict:
    """Provenance of a soak report: code, Hermes, gate and task versions, Harbor outcomes."""
    sha, dirty = git_state()
    jobs = {}
    for job in job_dirs:
        stats = json.loads((job / "result.json").read_text(encoding="utf-8")).get("stats", {})
        rewards = {}
        for trial in sorted(d for d in job.iterdir() if (d / "verifier" / "reward.json").is_file()):
            reward = json.loads((trial / "verifier" / "reward.json").read_text(encoding="utf-8"))
            rewards[trial.name] = reward.get("reward")
        jobs[rel(job)] = {
            "config_sha256": sha256_file(job / "config.json"),
            "completed_trials": stats.get("n_completed_trials"),
            "errored_trials": stats.get("n_errored_trials"),
            "retries": stats.get("n_retries"),
            "rewards": rewards,
        }
    return {
        "kind": "soak",
        "git_sha": sha,
        "git_dirty": dirty,
        "hermes_sha": hermes_sha(),
        "uv_lock_sha256": sha256_file(ROOT / "uv.lock"),
        "gate_sha256": sha256_file(ROOT / "configs" / "soak_gate.toml"),
        "tasks": {t: tree_sha256(tasks_dir / t.removeprefix("hjr/")) for t in task_ids},
        "jobs": jobs,
        "written_at": datetime.now(UTC).isoformat(),
    }


def write_manifest(run_dir: Path, record: RunManifest) -> None:
    text = record.model_dump_json(indent=2) + "\n"
    (run_dir / "manifest.json").write_text(text, encoding="utf-8", newline="\n")
