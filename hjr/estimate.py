"""Cost estimate for the Phase 2 plan, printed before any paid call.

Input tokens are prompt characters divided by the characters-per-token ratio measured in
`pilot-v1` (Flash cells: rebuilt prompts against provider-reported prompt tokens). Output tokens
come from `pilot-v1` where the same judge arm ran there, and otherwise from the stated
assumptions below, which are deliberately high for models that reason by default. Prices are
the pinned provider's current OpenRouter list prices (the highest one when the provider has
several tiers). Calls through the Codex CLI are not billed per call and cost $0 here.

repair-v1 does not exist yet; its prompts are estimated as the production prompt for the same
view plus REPAIR_EXTRA_CHARS of instructions.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import httpx

from hjr import judge
from hjr.config import ROOT, JudgeConfig
from hjr.judge import Variant
from hjr.phase2 import Plan, load_boundaries
from hjr.routes import ENDPOINTS_URL
from hjr.schemas import BoundaryRecord, JudgeVerdict, read_jsonl

PILOT_RUN = ROOT / "results" / "runs" / "pilot-v1"
PILOT_BOUNDARIES = ROOT / "data" / "frozen" / "pilot_boundaries.jsonl"
REPAIR_EXTRA_CHARS = 2500
# Output tokens per call where no measurement exists (reasoning included).
ASSUMED_OUTPUT_TOKENS = {"self-weak": 800, "self-strong": 600, "strong-api": 1500, "strong": 1500}


@dataclass(frozen=True)
class Line:
    arm: str
    variant: str
    calls: int
    tokens_in: float
    tokens_out: float
    out_source: str
    usd_per_call: float | None
    billed: bool

    @property
    def total(self) -> float | None:
        return None if self.usd_per_call is None else self.usd_per_call * self.calls


def measured_chars_per_token() -> float:
    """Prompt characters per provider-reported prompt token, from the pilot's Flash cells."""
    items = {b.boundary_id: b for b in read_jsonl(PILOT_BOUNDARIES, BoundaryRecord)}
    chars = tokens = 0
    path = PILOT_RUN / "judge" / "prod-plain__flash__head4k.jsonl"
    for v in read_jsonl(path, JudgeVerdict):
        if v.outcome == "no_call" or not v.tokens_in:
            continue
        messages = judge.build_messages(items[v.boundary_id], prompt="prod-plain", view="head4k")
        chars += sum(len(m["content"]) for m in messages)
        tokens += v.tokens_in
    return chars / tokens


def measured_output_tokens() -> dict[str, float]:
    """Mean output tokens per call in pilot-v1, by judge arm id."""
    sums: dict[str, list[int]] = {}
    for path in sorted((PILOT_RUN / "judge").glob("*.jsonl")):
        for v in read_jsonl(path, JudgeVerdict):
            if v.outcome != "no_call":
                sums.setdefault(v.arm_id, []).append(v.tokens_out)
    return {arm: sum(xs) / len(xs) for arm, xs in sums.items()}


def openrouter_price(model_id: str, provider: str, client: httpx.Client) -> tuple[float, float]:
    """(USD per prompt token, USD per completion token) on the pinned provider; highest tier."""
    resp = client.get(ENDPOINTS_URL.format(model=model_id))
    resp.raise_for_status()
    endpoints = (resp.json().get("data") or {}).get("endpoints") or []
    match = [e for e in endpoints if (e.get("tag") or "").split("/")[0] == provider]
    if not match:
        raise RuntimeError(f"{model_id} is not served by {provider}")
    return (
        max(float(e["pricing"]["prompt"]) for e in match),
        max(float(e["pricing"]["completion"]) for e in match),
    )


def prompt_chars(boundary: BoundaryRecord, variant: Variant) -> int:
    prompt = "prod-plain" if variant.prompt == "repair-v1" else variant.prompt
    messages = judge.build_messages(boundary, prompt=prompt, view=variant.view)
    extra = REPAIR_EXTRA_CHARS if variant.prompt == "repair-v1" else 0
    return sum(len(m["content"]) for m in messages) + extra


def estimate(
    plan: Plan,
    cfg: JudgeConfig,
    *,
    price: Callable[[str, str], tuple[float, float]],
    chars_per_token: float,
    pilot_output: dict[str, float],
) -> list[Line]:
    jobs: list[tuple[str, Variant, list[BoundaryRecord], int]] = []
    for arm in plan.arms:
        rows = load_boundaries(plan, arm)
        for v in plan.variants(arm):
            jobs.append((arm, v, rows, plan.samples))
        ids = set(plan.sanity_ids(arm))
        subset = [b for b in rows if b.boundary_id in ids]
        for spec in plan.sanity["variants"]:
            jobs.append((arm, Variant.parse(spec), subset, int(plan.sanity["samples"])))
    out = []
    for arm, v, rows, samples in jobs:
        model = cfg.model(v.model)
        called = [b for b in rows if b.last_response.strip()]
        calls = len(called) * samples
        tin = sum(prompt_chars(b, v) for b in called) / max(len(called), 1) / chars_per_token
        if model.arm_id in pilot_output:
            tout, source = pilot_output[model.arm_id], "pilot-v1"
        else:
            tout, source = ASSUMED_OUTPUT_TOKENS[v.model], "assumed"
        billed = cfg.endpoint(model).kind == "chat"
        if billed:
            p_in, p_out = price(model.model_id, model.provider)
            per_call = tin * p_in + tout * p_out
        else:
            per_call = 0.0
        out.append(Line(arm, str(v), calls, tin, tout, source, per_call, billed))
    return out


def render(lines: list[Line], chars_per_token: float) -> str:
    rows = [
        f"Prompt tokens from {chars_per_token:.2f} characters/token (measured, pilot-v1 Flash).",
        "",
        "| Arm | Variant | Calls | In tok/call | Out tok/call | Out source | $/call | $ total |",
        "|---|---|---|---|---|---|---|---|",
    ]
    paid = 0.0
    for ln in lines:
        cost = f"${ln.total:.2f}" if ln.billed else "$0 (subscription)"
        per = f"${ln.usd_per_call:.5f}" if ln.billed else "–"
        rows.append(
            f"| {ln.arm} | `{ln.variant}` | {ln.calls} | {ln.tokens_in:.0f} | "
            f"{ln.tokens_out:.0f} | {ln.out_source} | {per} | {cost} |"
        )
        paid += ln.total if ln.billed else 0.0
    calls = sum(ln.calls for ln in lines)
    cli = sum(ln.calls for ln in lines if not ln.billed)
    rows += [
        "",
        f"Total: {calls} calls ({cli} through the Codex CLI); billed estimate ${paid:.2f}.",
    ]
    return "\n".join(rows) + "\n"


def live_price() -> Callable[[str, str], tuple[float, float]]:
    client = httpx.Client(timeout=30)
    cache: dict[tuple[str, str], tuple[float, float]] = {}

    def price(model_id: str, provider: str) -> tuple[float, float]:
        key = (model_id, provider)
        if key not in cache:
            cache[key] = openrouter_price(model_id, provider, client)
        return cache[key]

    return price
