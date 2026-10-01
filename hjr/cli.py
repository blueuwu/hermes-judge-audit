"""Hermes goal-judge audit tools."""

from __future__ import annotations

import argparse
import logging
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from hjr import manifest
from hjr.config import ROOT, global_seed, load_judge_config
from hjr.judge import Variant
from hjr.schemas import BoundaryRecord, RunManifest, read_jsonl

RUNS = ROOT / "results" / "runs"


def cmd_replay(args: argparse.Namespace) -> int:
    from hjr.client import JudgeClient
    from hjr.replay import replay

    load_dotenv(ROOT / ".env")
    variants = [Variant.parse(v) for v in args.variant]
    cfg = load_judge_config()
    models = {v.model: cfg.model(v.model) for v in variants}
    clients = {key: JudgeClient(m).complete for key, m in models.items()}
    boundaries = list(read_jsonl(args.boundaries, BoundaryRecord))
    if args.limit:
        boundaries = boundaries[: args.limit]
    run_dir = RUNS / args.run_id

    git_sha, dirty = manifest.git_state()
    started = datetime.now(UTC)
    counts = replay(
        boundaries,
        variants,
        samples=args.samples,
        run_dir=run_dir,
        completions=clients,
        model_ids={k: m.id for k, m in models.items()},
        workers=args.workers,
    )
    record = RunManifest(
        run_id=args.run_id,
        kind="judge-replay",
        git_sha=git_sha,
        git_dirty=dirty,
        hermes_sha=manifest.hermes_sha(),
        uv_lock_sha256=manifest.sha256_file(ROOT / "uv.lock"),
        inputs={manifest.rel(args.boundaries): manifest.sha256_file(args.boundaries)},
        variants=[str(v) for v in variants],
        samples=args.samples,
        judge_config_sha256=cfg.sha256,
        models={k: m.describe() for k, m in models.items()},
        seed=global_seed(),
        started_at=started,
        finished_at=datetime.now(UTC),
        counts={"boundaries": len(boundaries), **counts},
    )
    (run_dir / "manifest.json").write_text(
        record.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"{args.run_id}: {dict(counts)}")
    return 1 if counts.get("failed") else 0


def cmd_pilot_build(args: argparse.Namespace) -> int:
    from hjr.pilot import build

    n = build.write(args.out)
    print(f"wrote {n} boundaries to {manifest.rel(args.out)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hjr", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("replay", help="replay judge variants over a boundaries file")
    p.add_argument("--boundaries", type=Path, required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument(
        "--variant", action="append", required=True, help="prompt:model:view (repeatable)"
    )
    p.add_argument("--samples", type=int, default=3)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--limit", type=int, default=0, help="first N boundaries only (smoke runs)")
    p.set_defaults(func=cmd_replay)

    p = sub.add_parser("pilot-build", help="write the constructed M0.5 pilot boundaries")
    p.add_argument("--out", type=Path, default=ROOT / "data" / "frozen" / "pilot_boundaries.jsonl")
    p.set_defaults(func=cmd_pilot_build)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)
