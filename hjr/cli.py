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
from hjr.schemas import BoundaryRecord, read_jsonl

RUNS = ROOT / "results" / "runs"
DEV_PREFIX = "dev-"


def cmd_replay(args: argparse.Namespace) -> int:
    from hjr.client import JudgeClient
    from hjr.ratelimit import Limiters
    from hjr.replay import replay

    load_dotenv(ROOT / ".env")
    variants = [Variant.parse(v) for v in args.variant]
    cfg = load_judge_config()
    arms = {v.model: cfg.model(v.model) for v in variants}
    dev = sorted(k for k, a in arms.items() if a.dev_only)
    if dev and not args.run_id.startswith(DEV_PREFIX):
        raise SystemExit(f"dev-only arms {dev} need a run id starting with {DEV_PREFIX!r}")
    if not dev and args.run_id.startswith(DEV_PREFIX):
        raise SystemExit(f"run ids starting with {DEV_PREFIX!r} are reserved for dev-only arms")
    limiters = Limiters({name: ep.rpm for name, ep in cfg.endpoints.items()})
    clients = {
        key: JudgeClient(
            arm,
            api_key_env=cfg.endpoint(arm).api_key_env,
            limiter=limiters.get(arm.endpoint),
        ).complete
        for key, arm in arms.items()
    }
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
        arms=arms,
        completions=clients,
        workers=args.workers,
    )
    record = manifest.judge_run_manifest(
        run_dir,
        git_sha=git_sha,
        git_dirty=dirty,
        boundaries_path=args.boundaries,
        n_boundaries=len(boundaries),
        variants=[str(v) for v in variants],
        samples=args.samples,
        arms=arms,
        judge_config_sha256=cfg.sha256,
        seed=global_seed(),
        started_at=started,
    )
    manifest.write_manifest(run_dir, record)
    print(f"{args.run_id}: {dict(counts)}")
    failed = counts.get("transport_failed") or counts.get("drift_incidents") or counts.get("halted")
    return 1 if failed else 0


def cmd_pilot_build(args: argparse.Namespace) -> int:
    from hjr.pilot import build

    n = build.write(args.out)
    print(f"wrote {n} boundaries to {manifest.rel(args.out)}")
    return 0


def cmd_pilot_summary(args: argparse.Namespace) -> int:
    from hjr.pilot import build, summarize

    out = summarize.summarize(build.OUTPUT, RUNS / args.run_id)
    print(out.read_text(encoding="utf-8"))
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

    p = sub.add_parser("pilot-summary", help="tabulate pilot verdicts into summary.md")
    p.add_argument("--run-id", default="pilot-v1")
    p.set_defaults(func=cmd_pilot_summary)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)
