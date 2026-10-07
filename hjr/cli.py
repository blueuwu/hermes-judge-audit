"""Hermes goal-judge audit tools."""

from __future__ import annotations

import argparse
import logging
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from hjr import manifest
from hjr.config import ROOT, check_self_judges, global_seed, load_judge_config
from hjr.judge import Variant
from hjr.schemas import BoundaryRecord, RunManifest, read_jsonl, require_single_phase

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
    boundaries = list(read_jsonl(args.boundaries, BoundaryRecord))
    phase = require_single_phase(boundaries)
    prev_path = RUNS / args.run_id / "manifest.json"
    if prev_path.exists():
        prev = RunManifest.model_validate_json(prev_path.read_text(encoding="utf-8"))
        if prev.phase != phase:
            raise ValueError("refusing to mix phases in a replay run")
    if args.split:
        boundaries = [b for b in boundaries if b.split == args.split]
    if args.limit:
        boundaries = boundaries[: args.limit]
    if args.subset == "sanity":
        from hjr.phase2 import load_plan

        arms_seen = {str(b.tags.get("agent_arm", "")) for b in boundaries}
        if len(arms_seen) != 1:
            raise SystemExit("--subset sanity needs boundaries from exactly one agent arm")
        ids = set(load_plan().sanity_ids(arms_seen.pop()))
        boundaries = [b for b in boundaries if b.boundary_id in ids]
        if len(boundaries) != len(ids):
            raise SystemExit("sanity subset ids not all found in these boundaries")
    try:
        agent_arms = {str(b.tags["agent_arm"]) for b in boundaries if "agent_arm" in b.tags}
        check_self_judges(cfg, arms, agent_arms)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    limiters = Limiters(cfg.limits())
    clients = {}
    for key, arm in arms.items():
        endpoint = cfg.endpoint(arm)
        limiter = limiters.get(cfg.limiter_key(key))
        if endpoint.kind == "codex":
            from hjr.codex import CodexClient

            client = CodexClient(arm, version=endpoint.version, limiter=limiter)
        else:
            client = JudgeClient(arm, api_key_env=endpoint.api_key_env, limiter=limiter)
        clients[key] = client.complete
    run_dir = RUNS / args.run_id

    git_sha, dirty = manifest.git_state()
    started = datetime.now(UTC)
    try:
        counts = replay(
            boundaries,
            variants,
            samples=args.samples,
            run_dir=run_dir,
            arms=arms,
            completions=clients,
            workers=args.workers,
        )
    except PermissionError as exc:
        raise SystemExit(f"refused: {exc}") from None
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
        phase=phase,
    )
    manifest.write_manifest(run_dir, record)
    print(f"{args.run_id}: {dict(counts)}")
    failed = counts.get("transport_failed") or counts.get("drift_incidents") or counts.get("halted")
    return 1 if failed else 0


def cmd_repair_design(args: argparse.Namespace) -> int:
    from hjr import repair, repair_design

    if args.iteration != repair.ITERATION:
        raise SystemExit(f"hjr/repair.py holds iteration {repair.ITERATION}, not {args.iteration}")
    status = 0
    if not args.report_only:
        git_sha, dirty = manifest.git_state()
        if dirty:
            raise SystemExit("commit the iteration's prompt before its run (prereg Amendment 3)")
        for source, path in repair_design.SOURCES.items():
            run = argparse.Namespace(
                boundaries=path,
                run_id=repair_design.run_id(args.iteration, source),
                variant=[repair_design.VARIANT],
                samples=repair_design.SAMPLES,
                workers=args.workers,
                limit=0,
                subset=None,
                split="dev",
            )
            status |= cmd_replay(run)
    out = repair_design.write_report(args.iteration)
    print(f"-> {manifest.rel(out)}")
    scores = repair_design.scores()
    if scores:
        print(f"selection rule over iterations {sorted(scores)}: {repair_design.select(scores)}")
    return status


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

    result = ingest_job(
        args.job, args.tasks, hermes_sha=hermes_sha(), harbor=version("harbor"), phase=args.phase
    )
    n = write_jsonl(args.out, result.boundaries)
    excluded = args.out.with_name(args.out.stem + ".excluded.json")
    excluded.write_bytes((json.dumps(result.excluded, indent=2) + "\n").encode("utf-8"))
    tasks = sorted({b.task_id for b in result.boundaries})
    record = ingest_manifest(
        args.job, args.tasks, tasks, boundaries=n, excluded=len(result.excluded), phase=args.phase
    )
    manifest_path = args.out.with_name(args.out.stem + ".manifest.json")
    manifest_path.write_bytes((json.dumps(record, indent=2) + "\n").encode("utf-8"))
    print(f"{n} boundaries -> {args.out}; {len(result.excluded)} exclusions -> {excluded}")
    return 0


def cmd_phase1b_estimate(args: argparse.Namespace) -> int:
    from hjr.enrichment import render, task_rates

    print(render(task_rates(args.boundaries, args.excluded), args.attempts, args.rates))
    return 0


def cmd_phase1b_select(args: argparse.Namespace) -> int:
    from hjr.enrichment import stage_b_tasks

    for task in stage_b_tasks(args.stage_a):
        print(task)
    return 0


def cmd_phase1b_pools(args: argparse.Namespace) -> int:
    from hjr.pools import report

    try:
        pools = args.judge_pool or ["dev"]
        text = report(args.stage_a, args.stage_b, pools, seed=str(global_seed()))
    except PermissionError as exc:
        print(f"refused: {exc}")
        return 2
    if args.out is None:
        print(text, end="")
    else:
        args.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"-> {args.out}")
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    from hjr.preflight import check_utf8

    problems = check_utf8()
    for problem in problems:
        print(f"FAIL {problem}")
    if not problems:
        print("ok utf8_mode=1, preferred encoding UTF-8")
    return 1 if problems else 0


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


def cmd_phase2_estimate(args: argparse.Namespace) -> int:
    from hjr import estimate
    from hjr.phase2 import load_plan

    ratio = estimate.measured_chars_per_token()
    lines = estimate.estimate(
        load_plan(),
        load_judge_config(),
        price=estimate.live_price(),
        chars_per_token=ratio,
        pilot_output=estimate.measured_output_tokens(),
    )
    print(estimate.render(lines, ratio))
    return 0


def cmd_phase2_summary(args: argparse.Namespace) -> int:
    from hjr import analysis
    from hjr.phase2 import load_boundaries, load_plan
    from hjr.replay import load_verdicts
    from hjr.schemas import AttemptRecord

    plan = load_plan()
    boundaries = {arm: load_boundaries(plan, arm) for arm in plan.arms}
    if args.truth == "v1":
        truth = {a: analysis.truth_from_verifier(boundaries[a]) for a in plan.arms}
    else:
        truth = {a: analysis.truth_from_file(plan.arms[a].boundaries) for a in plan.arms}

    def attempts(run_dir: Path) -> list:
        path = run_dir / "attempts.jsonl"
        return list(read_jsonl(path, AttemptRecord)) if path.exists() else []

    runs = {a: RUNS / spec.run_id for a, spec in plan.arms.items()}
    sanity = {}
    for arm in plan.arms:
        run_dir = RUNS / plan.sanity_run_id(arm)
        sanity[arm] = load_verdicts(run_dir) if run_dir.exists() else []
    report = analysis.analyse(
        plan,
        truth,
        boundaries,
        {a: load_verdicts(d) if d.exists() else [] for a, d in runs.items()},
        {a: attempts(d) for a, d in runs.items()},
        sanity,
    )
    out = RUNS / "phase2" / ("summary.md" if args.truth == "primary" else "summary-v1.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(analysis.render(report), encoding="utf-8", newline="\n")
    print(out.read_text(encoding="utf-8"))
    return 0


def cmd_regrade(args: argparse.Namespace) -> int:
    from hjr import regrade

    bad = 0
    for path in args.boundaries:
        out, not_reproduced = regrade.run(path.resolve())
        print(f"{path}: primary truth in {out.relative_to(ROOT)}")
        for r in not_reproduced:
            print(f"  NOT REPRODUCED {r.boundary_id}: v1 {r.v1_truth_state}, now {r.truth_state}")
        bad += len(not_reproduced)
    return 1 if bad else 0


def cmd_mutants(args: argparse.Namespace) -> int:
    from hjr import mutants
    from hjr.mutants import run

    if args.action == "check":
        problems = run.apply_check()
        n = len(mutants.load_all())
        print("\n".join(problems) or f"all {n} mutants apply and change their base")
        return 1 if problems else 0
    if args.action == "freeze":
        suite, added = mutants.freeze()
        print(f"suite {suite}: {len(added)} added")
        print("\n".join(f"  {a}" for a in added))
        return 0
    if args.action == "attribute":
        if not args.record:
            raise SystemExit("attribute needs --record results/mutants/<run>.jsonl")
        print(f"attribution in {run.reattribute(args.record.resolve()).relative_to(ROOT)}")
        return 0
    if args.action == "bases":
        results = run.grade_bases(args.task or None, workers=args.workers)
        versions = run.check_versions(b.task for b in results)
        for b in results:
            state = "ok" if b.ok else f"FAIL truth {b.truth}, failing {b.failing} {b.error[:300]}"
            print(f"{b.task} {versions[b.task][0]}: {state}")
        print(f"{sum(b.ok for b in results)}/{len(results)} bases grade as expected")
        return 0 if all(b.ok for b in results) else 1
    out, bases, rows = run.run(args.task or None, workers=args.workers, kinds=args.kind)
    bad = [b.task for b in bases if not b.ok]
    killed = sum(r["outcome"] == "killed_targeted" for r in rows)
    gated = sum(r["kind"] != "benign" for r in rows)
    print(f"bases: {len(bases) - len(bad)}/{len(bases)} as expected; failing: {bad or 'none'}")
    print(f"killed on target {killed}/{gated}; results in {out.relative_to(ROOT)}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    import json
    import os

    from hjr import audit

    if args.action == "draw":
        items = audit.load_metadata(args.boundaries)
        if len(items) != 178:
            raise ValueError("audit requires the complete 178-item Phase 1a population")
        log = audit.draw(
            items, args.verdicts, seed=global_seed(), primary_verifier=args.primary_verifier
        )
        audit.load_or_write_draw(args.draw, log)
        print(f"audit draw logged to {args.draw}; commit this file with the coordinator")
    else:
        log = json.loads(args.draw.read_text(encoding="utf-8"))
        if args.action == "report":
            print(audit.report(log, audit.load_records(args.records)), end="")
        else:
            if audit.load_metadata(args.boundaries) != {
                bid: audit.AuditItem.model_validate(item) for bid, item in log["items"].items()
            }:
                raise ValueError("boundary inputs differ from the audit draw")
            session = audit.Session(
                log,
                args.boundaries,
                args.records,
                args.annotator,
                workdir=args.workdir,
                jobs=args.jobs,
                tasks=args.tasks,
            )
            audit.run_pass(session, audit.Console(open=lambda p: os.startfile(p)))
    return 0


def cmd_pairs_build(args: argparse.Namespace) -> int:
    import importlib
    import json

    from hjr.pairs import BuildResult, ResponseEdit, read_dev, response_pairs, state_pairs
    from hjr.schemas import write_jsonl

    boundaries = read_dev(args.boundaries)
    out = args.out.resolve()
    for protected in ("tasks", "hjr/mutants", "data/frozen", "data/mutants", "results"):
        if out.is_relative_to(ROOT / protected):
            raise ValueError("pairs output must be outside frozen and research-result directories")
    if args.kind == "response":
        edits = list(read_jsonl(args.edits, ResponseEdit)) if args.edits else []
        result = BuildResult(items=response_pairs(boundaries, args.cell, edits))
    else:
        from hjr.mutants import load_all, require_frozen, retired

        if not args.executor or not args.snapshots:
            raise ValueError("state pairs need --snapshots and --executor module:factory")
        module, factory = args.executor.split(":")
        executor = getattr(importlib.import_module(module), factory)()
        require_frozen()
        retired_keys = retired()
        mutants = [m for m in load_all() if m.key not in retired_keys]
        snapshots = json.loads(args.snapshots.read_text(encoding="utf-8"))
        result = BuildResult()
        for boundary in boundaries:
            if boundary.boundary_id not in snapshots:
                raise ValueError("dev boundary missing from snapshot mapping")
            part = state_pairs(
                boundary, Path(snapshots[boundary.boundary_id]), mutants, args.cell, executor
            )
            result.items.extend(part.items)
            result.excluded.extend(part.excluded)
    write_jsonl(out, result.items)
    out.with_suffix(".excluded.json").write_text(
        json.dumps(result.excluded, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{len(result.items)} items; {len(result.excluded)} exclusions; {out}")
    return 0


def cmd_pairs_summary(args: argparse.Namespace) -> int:
    from hjr.pairs import PairItem
    from hjr.pairs_analysis import analyse, render
    from hjr.schemas import JudgeVerdict

    items = list(read_jsonl(args.items, PairItem))
    verdicts = list(read_jsonl(args.verdicts, JudgeVerdict))
    print(render(analyse(items, verdicts, tolerance=args.tolerance)), end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hjr", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    from hjr import audit

    p = sub.add_parser("audit", help="human verifier QA: draw, run, report (no model calls)")
    actions = p.add_subparsers(dest="action", required=True)
    for action in ("draw", "run", "report"):
        a = actions.add_parser(action)
        a.add_argument("--draw", type=Path, default=audit.DRAW)
        a.set_defaults(func=cmd_audit)
        if action in {"draw", "run"}:
            a.add_argument(
                "--boundaries",
                type=Path,
                action="append",
                required=True,
                help="primary-verifier Phase 1a JSONL (repeat for both arms)",
            )
        if action == "draw":
            a.add_argument(
                "--verdicts",
                type=Path,
                action="append",
                required=True,
                help="Phase 2 production-cell JSONL (repeat for both arms)",
            )
            a.add_argument(
                "--primary-verifier",
                required=True,
                help="frozen-primary verifier commit/note identifier",
            )
        else:
            a.add_argument("--records", type=Path, default=audit.RECORDS)
        if action == "run":
            a.add_argument("--annotator", required=True)
            a.add_argument("--workdir", type=Path, default=audit.WORKDIR)
            a.add_argument("--jobs", type=Path, default=audit.JOBS)
            a.add_argument("--tasks", type=Path, default=audit.TASKS)

    p = sub.add_parser("pairs-build", help="build dev controlled pairs (no judge calls)")
    p.add_argument("--boundaries", type=Path, required=True, help="dev-only JSONL")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--cell", action="append", required=True, help="prompt:model:view")
    p.add_argument("--kind", choices=["response", "state"], default="response")
    p.add_argument("--edits", type=Path, help="reviewed ResponseEdit JSONL for response pairs")
    p.add_argument(
        "--snapshots", type=Path, help="state: dev boundary id to extracted workspace JSON"
    )
    p.add_argument("--executor", help="state: module:factory implementing ReplayExecutor")
    p.set_defaults(func=cmd_pairs_build)

    p = sub.add_parser("pairs-summary", help="controlled-pairs analysis tables (no model calls)")
    p.add_argument("--items", type=Path, required=True)
    p.add_argument("--verdicts", type=Path, required=True)
    p.add_argument("--tolerance", type=float, help="dated, recorded E1 equivalence tolerance")
    p.set_defaults(func=cmd_pairs_summary)

    p = sub.add_parser("replay", help="replay judge variants over a boundaries file")
    p.add_argument("--boundaries", type=Path, required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument(
        "--variant", action="append", required=True, help="prompt:model:view (repeatable)"
    )
    p.add_argument("--samples", type=int, default=3)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--limit", type=int, default=0, help="first N boundaries only (smoke runs)")
    p.add_argument(
        "--subset",
        choices=["sanity"],
        help="only the preregistered subset of configs/phase2.toml for these boundaries' arm",
    )
    p.add_argument("--split", choices=["dev", "heldout"], help="only boundaries of this split")
    p.set_defaults(func=cmd_replay)

    p = sub.add_parser(
        "repair-design", help="one repair-v1 design iteration over the dev design set (Amendment 3)"
    )
    p.add_argument("--iteration", type=int, required=True)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument(
        "--report-only", action="store_true", help="rewrite the report from runs on disk"
    )
    p.set_defaults(func=cmd_repair_design)

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
    p.add_argument("--phase", choices=("1a", "1b-enrichment"), default="1a")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser(
        "phase1b-estimate", help="offline Stage A detection estimate from primary truth only"
    )
    p.add_argument("--boundaries", type=Path, default=ROOT / "data/frozen/phase1-weak.jsonl")
    p.add_argument("--excluded", type=Path, default=ROOT / "data/frozen/phase1-weak.excluded.json")
    p.add_argument("--attempts", type=int, default=20, help="Stage A attempts per task")
    p.add_argument("--rates", type=float, nargs="+", default=[0.02, 0.05, 0.10, 0.20])
    p.set_defaults(func=cmd_phase1b_estimate)

    p = sub.add_parser(
        "phase1b-select", help="Stage B tasks: C2-C4 with a primary-truth not-done in Stage A"
    )
    p.add_argument("--stage-a", type=Path, required=True, help="frozen Stage A boundaries")
    p.set_defaults(func=cmd_phase1b_select)

    p = sub.add_parser(
        "phase1b-pools", help="Phase 1b pool report under deviation-2 (refuses sealed pools)"
    )
    p.add_argument("--stage-a", type=Path, default=ROOT / "data/frozen/phase1b-weak-a.jsonl")
    p.add_argument("--stage-b", type=Path, default=ROOT / "data/frozen/phase1b-weak-b.jsonl")
    p.add_argument(
        "--judge-pool",
        action="append",
        choices=("dev", "heldout", "all"),
        help="Stage A+B selected-task pool for judge figures (default: dev)",
    )
    p.add_argument("--out", type=Path, help="write the report here instead of stdout")
    p.set_defaults(func=cmd_phase1b_pools, judge_pool=None)

    p = sub.add_parser("preflight", help="launch-environment checks before a paid job")
    p.set_defaults(func=cmd_preflight)

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

    p = sub.add_parser("phase2-estimate", help="estimated cost per Phase 2 cell (no model calls)")
    p.set_defaults(func=cmd_phase2_estimate)

    p = sub.add_parser("mutants", help="verifier mutation suite: check, freeze, bases, run, ...")
    p.add_argument("action", choices=["check", "freeze", "bases", "run", "attribute"])
    p.add_argument("--kind", action="append", choices=["req", "look", "con", "benign"])
    p.add_argument("--record", type=Path, help="attribute: a recorded run (.jsonl)")
    p.add_argument("--task", action="append", help="limit a run to these tasks")
    p.add_argument("--workers", type=int, default=4)
    p.set_defaults(func=cmd_mutants)

    p = sub.add_parser("regrade", help="regrade frozen boundaries at current verifier versions")
    p.add_argument("boundaries", type=Path, nargs="+", help="data/frozen/phase1-<arm>.jsonl")
    p.set_defaults(func=cmd_regrade)

    p = sub.add_parser("phase2-summary", help="Phase 2 analysis tables (no model calls)")
    p.add_argument(
        "--truth",
        choices=["primary", "v1"],
        default="primary",
        help="primary: the regraded truth in data/truth/; v1: as frozen at Phase 1 (sensitivity)",
    )
    p.set_defaults(func=cmd_phase2_summary)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)
