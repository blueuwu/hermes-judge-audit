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
    limiters = Limiters(cfg.limits())
    clients = {
        key: JudgeClient(
            arm,
            api_key_env=cfg.endpoint(arm).api_key_env,
            limiter=limiters.get(cfg.limiter_key(key)),
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


def cmd_probe_build(args: argparse.Namespace) -> int:
    from hjr.pilot import probes

    n = probes.write()
    print(f"wrote {n} format probes to {manifest.rel(probes.OUTPUT)}")
    return 0


def cmd_probe_summary(args: argparse.Namespace) -> int:
    from hjr.pilot import probes
    from hjr.replay import load_verdicts

    expected = {b.boundary_id: b.tags["expected"] for b in probes.build()}
    rows = [r for r in load_verdicts(RUNS / args.run_id) if r.boundary_id in expected]
    print(
        "| Variant | Calls | Parsed | Parse failed | Format violations | finish_reason=length "
        "| Verdict = expected |"
    )
    print("|---|---|---|---|---|---|---|")
    for variant in sorted({r.variant for r in rows}):
        vs = [r for r in rows if r.variant == variant]
        print(
            f"| `{variant}` | {len(vs)} | {sum(r.outcome == 'parsed' for r in vs)} | "
            f"{sum(r.outcome == 'parse_failed' for r in vs)} | "
            f"{sum(r.outcome == 'format_violation' for r in vs)} | "
            f"{sum(r.finish_reason == 'length' for r in vs)} | "
            f"{sum(r.verdict == expected[r.boundary_id] for r in vs)} |"
        )
    return 0


def cmd_pilot_summary(args: argparse.Namespace) -> int:
    from hjr.pilot import build, summarize

    out = summarize.summarize(build.OUTPUT, RUNS / args.run_id)
    print(out.read_text(encoding="utf-8"))
    return 0


def cmd_reparse(args: argparse.Namespace) -> int:
    from hjr.replay import reparse

    run_dir = RUNS / args.run_id
    out = run_dir / "reparsed"
    counts = reparse(run_dir, out)
    print(f"{manifest.rel(out)}: {dict(counts)}")
    return 0


def cmd_drift(args: argparse.Namespace) -> int:
    from hjr import drift
    from hjr.replay import load_verdicts

    run_dir = RUNS / args.run_id
    rows = load_verdicts(run_dir)
    pick = {str(Variant.parse(v)) for v in (args.baseline, args.candidate)}
    if len(pick) != 2:
        raise SystemExit("baseline and candidate must differ")
    base = [r for r in rows if r.variant == str(Variant.parse(args.baseline))]
    cand = [r for r in rows if r.variant == str(Variant.parse(args.candidate))]
    if not base or not cand:
        raise SystemExit("no verdicts for one of the variants in this run")
    boundaries = list(read_jsonl(args.boundaries, BoundaryRecord))
    report = drift.compare(boundaries, base, cand)
    path = drift.write(report, run_dir / "drift")
    print(path.read_text(encoding="utf-8"))
    return 0


def cmd_cost(args: argparse.Namespace) -> int:
    from hjr.replay import load_verdicts

    rows = [r for r in load_verdicts(RUNS / args.run_id) if r.outcome != "no_call"]
    if not rows:
        raise SystemExit("no model calls in this run")
    usage = manifest.usage_by_variant(rows)
    print(f"Measured in {args.run_id} (provider-billed cost):")
    for variant, u in sorted(usage.items()):
        calls = int(u["calls"])
        per_call = u["cost_usd"] / calls
        line = (
            f"  {variant}: {calls} calls, ${u['cost_usd']:.4f} total, ${per_call:.6f}/call, "
            f"{u['tokens_in'] / calls:.0f} in / {u['tokens_out'] / calls:.0f} out "
            f"({u['reasoning_tokens'] / calls:.0f} reasoning) tokens/call"
        )
        if u["calls_without_cost"]:
            line += f", {int(u['calls_without_cost'])} calls without billed cost"
        print(line)
        if args.calls:
            print(f"    extrapolated to {args.calls} calls: ${per_call * args.calls:.2f}")
            if args.input_tokens:
                scale = args.input_tokens / (u["tokens_in"] / calls)
                print(
                    f"    scaled to {args.input_tokens} input tokens/call "
                    f"(assumes cost ∝ input tokens): ${per_call * scale * args.calls:.2f}"
                )
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    import json
    from importlib.metadata import version

    from hjr.ingest import ingest_job
    from hjr.manifest import hermes_sha, ingest_manifest
    from hjr.schemas import write_jsonl

    result = ingest_job(args.job, args.tasks, hermes_sha=hermes_sha(), harbor=version("harbor"))
    n = write_jsonl(args.out, result.boundaries)
    excluded = args.out.with_name(args.out.stem + ".excluded.json")
    excluded.write_bytes((json.dumps(result.excluded, indent=2) + "\n").encode("utf-8"))
    tasks = sorted({b.task_id for b in result.boundaries})
    record = ingest_manifest(
        args.job, args.tasks, tasks, boundaries=n, excluded=len(result.excluded)
    )
    manifest_path = args.out.with_name(args.out.stem + ".manifest.json")
    manifest_path.write_bytes((json.dumps(record, indent=2) + "\n").encode("utf-8"))
    print(f"{n} boundaries -> {args.out}; {len(result.excluded)} exclusions -> {excluded}")
    return 0


def cmd_split(args: argparse.Namespace) -> int:
    from collections import Counter

    from hjr.split import SPLIT_CONFIG, write_split

    split = write_split(args.tasks)
    print(f"{dict(Counter(split.values()))} -> {SPLIT_CONFIG.relative_to(ROOT)}")
    return 0


def cmd_soak(args: argparse.Namespace) -> int:
    import copy
    import json
    import tomllib

    from hjr.manifest import soak_manifest
    from hjr.soak import evaluate, load_gate
    from hjr.soakreport import build_report

    gate = load_gate()
    built = build_report(args.job)
    result = evaluate(built.report, gate)
    # Informational: the same gate on the M1 tasks alone, without the soak-only workload.
    m1 = [
        t
        for t in gate["gate"]["tasks"]
        if not tomllib.loads(
            (args.tasks / t.removeprefix("hjr/") / "task.toml").read_text(encoding="utf-8")
        )["metadata"].get("soak_only")
    ]
    m1_gate = copy.deepcopy(gate)
    m1_gate["gate"]["tasks"] = m1
    try:
        m1_result = evaluate(build_report(args.job, tasks=set(m1)).report, m1_gate)
    except ValueError:  # no M1 trials in these jobs
        m1_result = None
    record = {
        "jobs": [j.as_posix() for j in args.job],
        "trials": built.trials,
        "gate": result.model_dump(),
        "m1_tasks_only": m1_result.model_dump() if m1_result else None,
        "by_task": built.by_task,
        "reasoning_echo": built.reasoning_echo,
        "report": built.report.model_dump(),
        "failed_turns": built.failed_turns,
        "context_by_trial": built.context_by_trial,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes((json.dumps(record, indent=2) + "\n").encode("utf-8"))
    manifest = soak_manifest(args.job, args.tasks, gate["gate"]["tasks"])
    args.out.with_suffix(".manifest.json").write_bytes(
        (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    )
    print(f"{built.report.arm_id}: {'PASS' if result.passed else 'FAIL'} ({built.trials} trials)")
    for key, value in result.counts.items():
        print(f"  {key}: {value}")
    for failure in result.failures:
        print(f"  failure: {failure}")
    for failed in built.failed_turns:
        print(f"  infrastructure failure: {failed}")
    for task, summary in built.by_task.items():
        print(
            f"  {task}: {summary['trials']} trials, {summary['tool_calls']} tool calls, "
            f"context t5 {summary['context_turn_5']} t6 {summary['context_turn_6']}"
        )
    if m1_result:
        print(f"  M1 tasks only: {'PASS' if m1_result.passed else 'FAIL'} {m1_result.failures}")
    echo = built.reasoning_echo
    print(
        f"  reasoning_content round trip ({'replayed' if echo['echo_expected'] else 'stripped'}): "
        f"{'PASS' if echo['passed'] else 'FAIL'} "
        + ", ".join(f"{k}={v}" for k, v in echo.items() if k not in ("echo_expected", "passed"))
    )
    return 0 if result.passed else 1


def cmd_check_route(args: argparse.Namespace) -> int:
    from hjr.routes import check_routes

    ok = True
    for line, good in check_routes(load_judge_config(), args.model):
        ok &= good
        print(("ok    " if good else "FAIL  ") + line)
    return 0 if ok else 1


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

    p = sub.add_parser("probe-build", help="write the format-compliance probe items")
    p.set_defaults(func=cmd_probe_build)

    p = sub.add_parser("probe-summary", help="format-compliance table for a probe run")
    p.add_argument("--run-id", default="probe-v1")
    p.set_defaults(func=cmd_probe_summary)

    p = sub.add_parser("pilot-summary", help="tabulate pilot verdicts into summary.md")
    p.add_argument("--run-id", default="pilot-v1")
    p.set_defaults(func=cmd_pilot_summary)

    p = sub.add_parser("reparse", help="re-parse stored raw judge responses (no model calls)")
    p.add_argument("--run-id", required=True)
    p.set_defaults(func=cmd_reparse)

    p = sub.add_parser("drift", help="compare two judge arms on the same frozen items")
    p.add_argument("--run-id", required=True)
    p.add_argument("--boundaries", type=Path, required=True)
    p.add_argument("--baseline", required=True, help="prompt:model:view")
    p.add_argument("--candidate", required=True, help="prompt:model:view")
    p.set_defaults(func=cmd_drift)

    p = sub.add_parser("cost", help="measured token use and spend, with extrapolation")
    p.add_argument("--run-id", required=True)
    p.add_argument("--calls", type=int, default=0, help="planned calls to extrapolate to")
    p.add_argument("--input-tokens", type=int, default=0, help="planned mean input tokens/call")
    p.set_defaults(func=cmd_cost)

    p = sub.add_parser("ingest", help="Harbor job -> BoundaryRecords (verifier truth joined)")
    p.add_argument("--job", type=Path, required=True, help="jobs/<job name>")
    p.add_argument("--tasks", type=Path, default=Path("tasks"))
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("split", help="write the seeded dev/held-out task split")
    p.add_argument("--tasks", type=Path, default=Path("tasks"))
    p.set_defaults(func=cmd_split)

    p = sub.add_parser("soak", help="evaluate one agent arm's soak jobs against the gate")
    p.add_argument("--job", type=Path, action="append", required=True, help="jobs/<name>")
    p.add_argument("--tasks", type=Path, default=Path("tasks"))
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=cmd_soak)

    p = sub.add_parser(
        "check-route", help="verify pinned models and providers are listed (metadata only)"
    )
    p.add_argument("--model", action="append", help="model key (default: all non-dev arms)")
    p.set_defaults(func=cmd_check_route)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)
