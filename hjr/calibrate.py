"""Offline calibration planning and a guarded adapter to the existing replay engine."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from hermes_cli import goals as hg

from hjr import judge
from hjr.config import CONFIGS, ROOT, load_judge_config
from hjr.replay import replay
from hjr.schemas import BoundaryRecord, read_jsonl, require_single_phase

CONFIG = CONFIGS / "calibrate.toml"
STOP_USD = Decimal("20")
TEMPLATES = {
    name: getattr(hg, name)
    for name in (
        "JUDGE_USER_PROMPT_WITH_CONTRACT_TEMPLATE",
        "JUDGE_USER_PROMPT_WITH_SUBGOALS_TEMPLATE",
    )
}


def compute_metrics(decisions, truth):
    """Integration point for the per-class precision/recall table code (PR #11) once merged."""
    return NotImplemented


def usd(value) -> Decimal:
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0:
        raise ValueError("USD amounts must be finite and nonnegative")
    return amount


def run_path(runs: Path, name: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        raise ValueError("run id must be a directory name")
    path = (runs / name).resolve()
    if path.parent != runs.resolve() or not path.is_dir():
        raise ValueError(f"existing run directory required: {name}")
    return path


def stored_endpoints(run_dir: Path) -> list[BoundaryRecord]:
    """Select unique endpoints actually represented in this run's verdict files."""
    record = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    ids = set()
    for path in sorted((run_dir / "judge").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            ids.add(json.loads(line)["boundary_id"])
    found = {}
    for name, expected_hash in record["inputs"].items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT.resolve()):
            raise ValueError("source input must be inside the repository")
        # Inputs are text with canonical LF in git, including on Windows.
        digest = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        if digest != expected_hash:
            raise ValueError(f"source input hash changed: {name}")
        for boundary in read_jsonl(path, BoundaryRecord):
            if boundary.boundary_id in ids:
                if boundary.boundary_id in found and found[boundary.boundary_id] != boundary:
                    raise ValueError("conflicting source endpoints")
                found[boundary.boundary_id] = boundary
    if not ids or set(found) != ids:
        raise ValueError("source endpoints missing from manifest inputs or judge records")
    boundaries = list(found.values())
    require_single_phase(boundaries)
    return boundaries


@dataclass
class Plan:
    source: str
    agent_arm: str
    name: str
    spec: dict
    boundaries: list[BoundaryRecord]
    estimate: Decimal

    @property
    def calls(self) -> int:
        return len(self.boundaries) * self.spec["samples"]


def plans(from_run: str, names: list[str] | None, runs: Path, data: dict) -> list[Plan]:
    run_path(runs, from_run)
    selected = names or list(data["variants"])
    if len(set(selected)) != len(selected) or any(n not in data["variants"] for n in selected):
        raise ValueError("variant names must be unique and present in calibrate.toml")
    out = []
    for source in data.get("source_runs", {}).get(from_run, [from_run]):
        boundaries = stored_endpoints(run_path(runs, source))
        groups = {}
        for b in boundaries:
            groups.setdefault(str(b.tags.get("agent_arm", "constructed")), []).append(b)
        for name in selected:
            spec = data["variants"][name]
            if spec["template"] not in TEMPLATES or spec["view"] not in judge.VIEWS:
                raise ValueError(f"unsupported template or view: {name}")
            if type(spec["samples"]) is not int or spec["samples"] < 1:
                raise ValueError("samples must be a positive integer")
            price = usd(data["stub_prices"][spec["model"]])
            for agent_arm, items in sorted(groups.items()):
                out.append(
                    Plan(source, agent_arm, name, spec, items, price * len(items) * spec["samples"])
                )
    return out


def cumulative_spend(path: Path) -> Decimal:
    text = path.read_text(encoding="utf-8")
    totals = re.findall(r"^\| \*\*Total\*\* \|[^|]*\| \*\*\$([0-9.]+)\*\* \|", text, re.M)
    if len(totals) != 1:
        raise ValueError("spend.md must contain exactly one billed Total row")
    return usd(totals[0])


def guard_spend(estimate: Decimal, cap, spend_path: Path) -> None:
    if cap is None:
        raise ValueError("--live requires an explicit --confirm-spend USD cap")
    if estimate > usd(cap):
        raise ValueError("estimate exceeds --confirm-spend cap")
    if cumulative_spend(spend_path) + estimate > STOP_USD:
        raise ValueError("cumulative spend plus estimate exceeds the pre-registered $20 stop")


def messages(boundary, *, prompt, view, specs):
    spec = specs[prompt]
    common = dict(
        goal=hg._truncate(boundary.goal, judge.GOAL_CHARS),
        response=judge.apply_view(view, boundary),
        background_block=judge.render_background_block(
            boundary.background_processes, boundary.active_delegations
        ),
        current_time=judge.format_time(boundary.ts),
    )
    if spec.get("needs_per_task_contract"):
        block = hg.GoalContract.from_dict(
            spec.get("contracts", {}).get(boundary.task_id)
        ).render_block()
        if not block:
            raise ValueError(f"{prompt} needs an independently authored per-task contract")
        common["contract_block"] = hg._truncate(block, judge.CONTRACT_CHARS)
    else:
        criteria = spec.get("subgoals", {}).get(boundary.task_id, [])
        if not criteria or not all(isinstance(c, str) and c.strip() for c in criteria):
            raise ValueError(f"{prompt} needs per-task subgoals")
        common["subgoals_block"] = hg._truncate(
            "\n".join(f"{i}. {c}" for i, c in enumerate(criteria, 1)), 2000
        )
    return [
        {"role": "system", "content": hg.JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": TEMPLATES[spec["template"]].format(**common)},
    ]


def execute(args, runs: Path) -> int:
    raw = CONFIG.read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))
    names = [n for value in args.variants for n in value.split(",")] if args.variants else None
    schedule = plans(args.from_run, names, runs, data)
    cfg = load_judge_config(CONFIG)  # Never loads the frozen judge_variants.toml.
    for plan in schedule:
        cfg.model(plan.spec["model"])
    print("STUB PRICES (USD per call): estimates only, not provider quotes or billing bounds.")
    print("| Source run | Agent arm | Variant | Items | Calls (items x samples) | Estimated USD |")
    print("|---|---|---|---:|---:|---:|")
    for p in schedule:
        print(
            f"| {p.source} | {p.agent_arm} | {p.name} | {len(p.boundaries)} | "
            f"{p.calls} | ${p.estimate:.4f} |"
        )
    if not args.live:
        return 0
    estimate = sum((p.estimate for p in schedule), Decimal(0))
    guard_spend(estimate, args.confirm_spend, runs / "phase2" / "spend.md")

    # Preflight every prompt before constructing any client or writing output.
    def builder(boundary, *, prompt, view):
        return messages(boundary, prompt=prompt, view=view, specs=data["variants"])

    for p in schedule:
        for b in p.boundaries:
            builder(b, prompt=p.name, view=p.spec["view"])
    from hjr.client import JudgeClient
    from hjr.ratelimit import Limiters

    limiters = Limiters(cfg.limits())
    keys = {p.spec["model"] for p in schedule}
    clients = {
        key: JudgeClient(
            cfg.model(key),
            api_key_env=cfg.endpoint(cfg.model(key)).api_key_env,
            limiter=limiters.get(cfg.limiter_key(key)),
        ).complete
        for key in keys
    }
    batch = uuid4().hex
    status = 0
    for i, p in enumerate(schedule):
        out = runs / f"calibrate-{batch}-{i}"
        counts = replay(
            p.boundaries,
            [judge.Variant(p.name, p.spec["model"], p.spec["view"])],
            samples=p.spec["samples"],
            run_dir=out,
            arms=cfg.models,
            completions=clients,
            build_messages=builder,
        )
        out.mkdir(parents=True, exist_ok=True)
        (out / "calibration.json").write_text(
            json.dumps(
                dict(
                    source=p.source,
                    agent_arm=p.agent_arm,
                    variant=p.name,
                    config_sha256=cfg.sha256,
                    estimate_usd=str(p.estimate),
                    confirm_spend=str(args.confirm_spend),
                    counts=dict(counts),
                ),
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (out / "calibrate.toml").write_bytes(raw)
        status |= bool(counts["transport_failed"] or counts["drift_incidents"] or counts["halted"])
    return int(status)
