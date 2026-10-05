"""The frozen Phase 2 plan (`configs/phase2.toml`): cells per agent arm, seeds, sanity subset.

A cell is written with the model key `self`, which resolves to the arm's own self judge
(`self-weak` on weak boundaries, `self-strong` on strong ones). Variants are recorded with the
resolved key, so records from the two self judges carry different arm ids and are never pooled.
"""

from __future__ import annotations

import random
import tomllib
from dataclasses import dataclass
from pathlib import Path

from hjr.config import CONFIGS, ROOT, global_seed
from hjr.judge import Variant
from hjr.schemas import BoundaryRecord, read_jsonl, require_single_phase

PLAN_CONFIG = CONFIGS / "phase2.toml"
SELF = "self"


@dataclass(frozen=True)
class ArmPlan:
    name: str
    boundaries: Path
    run_id: str


@dataclass(frozen=True)
class Plan:
    samples: int
    arms: dict[str, ArmPlan]
    cells: list[str]
    identical: dict[str, str]
    seeds: dict[str, str]
    sanity: dict

    def seed(self, stream: str) -> str:
        """Seed for a named stream: '<global seed>:<stream name>'."""
        return f"{global_seed()}:{self.seeds[stream]}"

    def variants(self, arm: str) -> list[Variant]:
        return [resolve(cell, arm) for cell in self.cells]

    def sanity_run_id(self, arm: str) -> str:
        return f"{self.sanity['run_id']}-{arm}"

    def sanity_ids(self, arm: str) -> list[str]:
        return list(self.sanity.get("ids", {}).get(arm, []))


def load_plan(path: Path = PLAN_CONFIG) -> Plan:
    doc = tomllib.loads(path.read_text(encoding="utf-8"))
    arms = {
        name: ArmPlan(name, ROOT / spec["boundaries"], spec["run_id"])
        for name, spec in doc["arms"].items()
    }
    plan = Plan(
        samples=int(doc["samples"]),
        arms=arms,
        cells=list(doc["cells"]["run"]),
        identical=dict(doc["cells"].get("identical", {})),
        seeds=dict(doc["seeds"]),
        sanity=dict(doc["sanity"]),
    )
    for cell in plan.cells + list(plan.identical) + list(plan.identical.values()):
        for arm in plan.arms:
            resolve(cell, arm)  # validates prompt and view
    return plan


def resolve(cell: str, arm: str) -> Variant:
    prompt, model, view = cell.split(":")
    if model == SELF:
        model = f"self-{arm}"
    return Variant.parse(f"{prompt}:{model}:{view}")


def cell_of(variant: str) -> str:
    """The plan cell a recorded variant belongs to (self-weak / self-strong -> self)."""
    v = Variant.parse(variant)
    model = SELF if v.model.startswith("self-") else v.model
    return f"{v.prompt}:{model}:{v.view}"


def load_boundaries(plan: Plan, arm: str) -> list[BoundaryRecord]:
    rows = list(read_jsonl(plan.arms[arm].boundaries, BoundaryRecord))
    require_single_phase(rows)
    return rows


def draw_sanity(plan: Plan, boundaries: dict[str, list[BoundaryRecord]]) -> dict[str, list[str]]:
    """Seeded draw of the harness sanity subset, stratified by verifier truth within each arm."""
    if require_single_phase(b for rows in boundaries.values() for b in rows) != "1a":
        raise ValueError("the frozen sanity subset is Phase 1a only")
    per_arm, not_done = int(plan.sanity["per_arm"]), int(plan.sanity["not_done"])
    out = {}
    for arm in sorted(boundaries):
        rows = boundaries[arm]
        neg = sorted(b.boundary_id for b in rows if b.verifier.truth_state != "done")
        pos = sorted(b.boundary_id for b in rows if b.verifier.truth_state == "done")
        rng = random.Random(f"{plan.seed('sanity')}:{arm}")
        picked = rng.sample(neg, not_done) + rng.sample(pos, per_arm - not_done)
        out[arm] = sorted(picked)
    return out
