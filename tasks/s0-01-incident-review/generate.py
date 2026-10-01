# ruff: noqa: E501  (artifact prose and table rows are kept on one line each)
"""Generate the staged evidence, hidden answers and reference report for s0-01-incident-review.

Soak-only workload (configs/prereg.md, 2026-10-01 coverage amendment). Deterministic from the
global seed: running this file rewrites environment/workspace/README.md, stages/,
tests/expected.json and solution/incident.json byte for byte, and tests/test_tasks.py checks
that the committed files match. Every answer is computed from the generated records.

The incident: payments v41 (deploy D-2291) shrank the database pool from 50 to 5 and switched
ledger idempotency to log-only. The pool saturated, checkout timed out on payments and retried,
and payments captured some abandoned charges late, so some orders were charged twice and some
failed orders were charged once. Inventory failures and other deploys are unrelated noise.
"""

from __future__ import annotations

import hashlib
import json
import random
import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = tomllib.loads((HERE.parents[1] / "configs" / "seeds.toml").read_text(encoding="utf-8"))[
    "global"
]


def t(hh: int, mm: int, ss: int = 0, ms: int = 0) -> datetime:
    return datetime(2026, 9, 14, hh, mm, ss, ms * 1000, tzinfo=UTC)


def iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def hms(ts: datetime) -> str:
    return ts.strftime("%H:%M:%S")


def hm(ts: datetime) -> str:
    return ts.strftime("%H:%M")


DEPLOY_START, DEPLOY_DONE = t(13, 41, 5), t(13, 52, 40)
IDEM_OFF = t(13, 44, 30)  # first payments pod on v41
ROLLBACK_START, ROLLBACK_DONE = t(14, 47, 10), t(14, 53, 20)
WINDOW_START, WINDOW_END = t(13, 55), t(15, 5)
LEDGER_START = t(13, 46)
SATURATED = (t(14, 6), t(14, 52))  # first and last saturated minute
INCIDENT = (t(14, 7), t(14, 53))  # checkout attempts that can time out start in here
INVENTORY_FAILS = (t(13, 58), t(14, 31), t(15, 1))
CLIENT_TIMEOUT = timedelta(seconds=8)


@dataclass
class Order:
    order: str
    trace: str
    amount: float
    start: datetime
    outcome: str = "ok"  # ok | slow_ok | timeout_fail | retry_ok | inventory_fail
    late_capture: bool = False  # payments captured attempt 1 after checkout gave up
    charges: list[str] = field(default_factory=list)
    end: datetime | None = None


class Gen:
    def __init__(self) -> None:
        self.rng = random.Random(SEED)
        self.used: set[str] = set()

    def uid(self, prefix: str, lo: int, hi: int) -> str:
        while True:
            v = f"{prefix}{self.rng.randint(lo, hi)}"
            if v not in self.used:
                self.used.add(v)
                return v

    def trace(self) -> str:
        while True:
            v = f"{self.rng.getrandbits(32):08x}"
            if v not in self.used:
                self.used.add(v)
                return v

    def ms(self, lo: int, hi: int) -> timedelta:
        return timedelta(milliseconds=self.rng.randint(lo, hi))


# ── The underlying event model ─────────────────────────────────────────────────────────────────


def build_orders(g: Gen) -> list[Order]:
    orders: list[Order] = []
    minute = LEDGER_START
    while minute < WINDOW_END:
        n = 1 if g.rng.random() < 0.7 else 0
        if minute >= WINDOW_START and g.rng.random() < 0.05:
            n += 1
        for _ in range(n):
            start = minute + timedelta(
                seconds=g.rng.randint(0, 59), milliseconds=g.rng.randint(0, 999)
            )
            orders.append(
                Order(
                    g.uid("ORD-", 40000, 59999), g.trace(), round(g.rng.uniform(12, 240), 2), start
                )
            )
        minute += timedelta(minutes=1)
    orders.sort(key=lambda o: o.start)

    for when in INVENTORY_FAILS:
        o = min((o for o in orders if o.start >= WINDOW_START), key=lambda o: abs(o.start - when))
        o.outcome = "inventory_fail"
    incident = [
        o for o in orders if INCIDENT[0] <= o.start < INCIDENT[1] and o.outcome != "inventory_fail"
    ]
    for i, o in enumerate(incident):
        r = g.rng.random()
        o.outcome = "timeout_fail" if i == 0 or r < 0.55 else "retry_ok" if r < 0.72 else "slow_ok"
    retried = [o for o in incident if o.outcome == "retry_ok"]
    failed = [o for o in incident if o.outcome == "timeout_fail"]
    for o in g.rng.sample(retried, 4) + g.rng.sample(failed[1:], 3):
        o.late_capture = True

    for o in orders:
        if o.outcome == "ok":
            o.end = o.start + g.ms(240, 950)
        elif o.outcome == "slow_ok":
            o.end = o.start + g.ms(5200, 7900)
        elif o.outcome == "inventory_fail":
            o.end = o.start + g.ms(90, 210)
        elif o.outcome == "retry_ok":
            o.end = o.start + CLIENT_TIMEOUT + g.ms(2100, 6500)
        else:
            o.end = o.start + 2 * CLIENT_TIMEOUT + g.ms(4, 40)
        if o.outcome != "inventory_fail":
            o.charges.append(g.uid("CHG-", 70000, 99999))
        if o.outcome in ("retry_ok", "timeout_fail"):
            o.charges.append(g.uid("CHG-", 70000, 99999))
    return orders


@dataclass
class Capture:
    ts: datetime
    order: Order
    charge: str
    node: str


def payments_events(g: Gen, orders: list[Order]) -> tuple[list[str], list[Capture]]:
    """Charge log lines (slow, retried or not captured) and every ledger capture."""
    lines: list[tuple[datetime, str]] = []
    captures: list[Capture] = []
    for o in orders:
        node = f"payments-{g.rng.randint(1, 3)}"
        if o.outcome in ("ok", "slow_ok"):
            done = o.end - g.ms(30, 120)
            captures.append(Capture(done, o, o.charges[0], node))
            if o.outcome == "slow_ok":
                lat = int((done - o.start).total_seconds() * 1000)
                lines.append(
                    (
                        done,
                        f"{node} INFO charge={o.charges[0]} order={o.order} attempt=1 "
                        f"status=captured latency_ms={lat} client=ok",
                    )
                )
        elif o.outcome in ("retry_ok", "timeout_fail"):
            first, second = o.charges
            if o.late_capture:
                done = o.start + CLIENT_TIMEOUT + g.ms(900, 5200)
                lat = int((done - o.start).total_seconds() * 1000)
                captures.append(Capture(done, o, first, node))
                lines.append(
                    (
                        done,
                        f"{node} INFO charge={first} order={o.order} attempt=1 "
                        f"status=captured latency_ms={lat} client=gone",
                    )
                )
            else:
                done = o.start + CLIENT_TIMEOUT + g.ms(1500, 3000)
                lines.append(
                    (
                        done,
                        f"{node} WARN charge={first} order={o.order} attempt=1 "
                        f"status=abandoned reason=pool_wait_exceeded wait_ms={g.rng.randint(9000, 11000)}",
                    )
                )
            retry_at = o.start + CLIENT_TIMEOUT
            if o.outcome == "retry_ok":
                done2 = o.end - g.ms(30, 120)
                lat = int((done2 - retry_at).total_seconds() * 1000)
                captures.append(Capture(done2, o, second, node))
                lines.append(
                    (
                        done2,
                        f"{node} INFO charge={second} order={o.order} attempt=2 "
                        f"status=captured latency_ms={lat} client=ok",
                    )
                )
            else:
                done2 = retry_at + CLIENT_TIMEOUT + g.ms(1500, 3000)
                lines.append(
                    (
                        done2,
                        f"{node} WARN charge={second} order={o.order} attempt=2 "
                        f"status=abandoned reason=pool_wait_exceeded wait_ms={g.rng.randint(9000, 11000)}",
                    )
                )
    lines = [(ts, ln) for ts, ln in lines if WINDOW_START <= ts < WINDOW_END]
    return [f"{iso(ts)} {ln}" for ts, ln in sorted(lines)], sorted(captures, key=lambda c: c.ts)


def pool_rows(g: Gen) -> list[dict]:
    rows = []
    minute = WINDOW_START
    while minute < WINDOW_END:
        max_size = 5 if minute < ROLLBACK_DONE.replace(second=0) else 50
        if SATURATED[0] <= minute <= SATURATED[1]:
            in_use, waiters, wait = 5, g.rng.randint(2, 14), g.rng.randint(1500, 9000)
        elif minute < SATURATED[0]:
            in_use, waiters, wait = (
                min(4, 2 + (minute - WINDOW_START).seconds // 180),
                0,
                g.rng.randint(0, 40),
            )
        else:
            in_use, waiters, wait = g.rng.randint(6, 14), 0, g.rng.randint(0, 30)
        rows.append(
            {
                "minute": hm(minute),
                "in_use": in_use,
                "max_size": max_size,
                "waiters": waiters,
                "max_wait_ms": wait,
            }
        )
        minute += timedelta(minutes=1)
    peak = next(r for r in rows if r["minute"] == "14:38")
    peak["waiters"], peak["max_wait_ms"] = 17, 11840
    return rows


# ── Artifacts ─────────────────────────────────────────────────────────────────────────────────


def edge_log(g: Gen, orders: list[Order]) -> list[str]:
    status = {
        "ok": 200,
        "slow_ok": 200,
        "retry_ok": 200,
        "timeout_fail": 504,
        "inventory_fail": 502,
    }
    lines: list[tuple[datetime, str]] = []
    for o in orders:
        if o.start < WINDOW_START:
            continue
        dur = int((o.end - o.start).total_seconds() * 1000)
        lines.append(
            (
                o.end,
                f"edge-{g.rng.randint(1, 2)} POST /api/checkout status={status[o.outcome]} "
                f"dur_ms={dur} trace={o.trace} order={o.order}",
            )
        )
    background = [
        ("GET", "/api/products", (200, 200, 200, 304)),
        ("GET", "/api/cart", (200,)),
        ("POST", "/api/cart/items", (200, 200, 200, 404)),
        ("GET", "/api/orders/{id}", (200, 200, 404)),
    ]
    for _ in range(24):
        ts = WINDOW_START + timedelta(
            seconds=g.rng.randint(0, 69 * 60), milliseconds=g.rng.randint(0, 999)
        )
        method, path, codes = g.rng.choice(background)
        path = path.replace("{id}", g.uid("ORD-", 30000, 39999))
        lines.append(
            (
                ts,
                f"edge-{g.rng.randint(1, 2)} {method} {path} status={g.rng.choice(codes)} "
                f"dur_ms={g.rng.randint(18, 260)} trace={g.trace()}",
            )
        )
    return [f"{iso(ts)} {ln}" for ts, ln in sorted(lines)]


def checkout_log(g: Gen, orders: list[Order]) -> list[str]:
    lines: list[tuple[datetime, str]] = []
    for o in orders:
        if o.start < WINDOW_START:
            continue
        node = f"checkout-{g.rng.randint(1, 3)}"
        if o.outcome == "inventory_fail":
            lines.append(
                (
                    o.end,
                    f"{node} ERROR order={o.order} trace={o.trace} "
                    "code=INVENTORY_UNAVAILABLE upstream=inventory attempts=1 status=failed",
                )
            )
        if o.outcome in ("retry_ok", "timeout_fail"):
            warn = o.start + CLIENT_TIMEOUT
            lines.append(
                (
                    warn,
                    f"{node} WARN order={o.order} trace={o.trace} attempt=1 "
                    "code=PAYMENT_UPSTREAM_TIMEOUT upstream=payments elapsed_ms=8000 action=retry",
                )
            )
            if o.outcome == "retry_ok":
                lines.append(
                    (
                        o.end,
                        f"{node} INFO order={o.order} trace={o.trace} attempt=2 "
                        f"status=ok charge={o.charges[1]}",
                    )
                )
            else:
                lines.append(
                    (
                        o.end,
                        f"{node} ERROR order={o.order} trace={o.trace} "
                        "code=PAYMENT_UPSTREAM_TIMEOUT upstream=payments attempts=2 status=failed",
                    )
                )
    noise = [
        "WARN inventory lookup slow sku_batch=12 elapsed_ms={n}",
        "WARN cart cache miss ratio={r} window=60s",
        "WARN promo service returned stale ruleset age_s={n}",
    ]
    for _ in range(5):
        ts = WINDOW_START + timedelta(
            seconds=g.rng.randint(0, 69 * 60), milliseconds=g.rng.randint(0, 999)
        )
        text = g.rng.choice(noise).format(
            n=g.rng.randint(300, 2400), r=f"{g.rng.uniform(0.2, 0.5):.2f}"
        )
        lines.append((ts, f"checkout-{g.rng.randint(1, 3)} {text}"))
    return [f"{iso(ts)} {ln}" for ts, ln in sorted(lines)]


def ledger_log(g: Gen, captures: list[Capture]) -> list[str]:
    lines: list[tuple[datetime, str]] = []
    n = 77100
    for c in captures:
        n += g.rng.randint(1, 3)
        at = c.ts + g.ms(120, 400)
        idem = "none" if IDEM_OFF <= at < ROLLBACK_DONE else f"k-{g.rng.getrandbits(40):010x}"
        lines.append(
            (
                at,
                f"ledger-1 INFO entry=LE-{n} type=CAPTURE order={c.order.order} "
                f"charge={c.charge} amount={c.order.amount:.2f} idem={idem} src={c.node}",
            )
        )
    for when, order, amount in (
        (t(13, 49, 2, 410), "ORD-31877", 64.10),
        (t(14, 41, 37, 95), "ORD-30562", 18.99),
    ):
        n += 1
        lines.append(
            (
                when,
                f"ledger-1 INFO entry=LE-{n} type=REFUND order={order} "
                f"charge={g.uid('CHG-', 60000, 69999)} amount=-{amount:.2f} idem=k-{g.rng.getrandbits(40):010x} src=support",
            )
        )
    for k in range(6):
        when = t(13, 45) + timedelta(minutes=15 * k, seconds=2)
        lines.append(
            (
                when,
                f"ledger-1 INFO settlement batch=SB-{4410 + k} entries_closed={g.rng.randint(9, 19)} status=ok",
            )
        )
    return [f"{iso(ts)} {ln}" for ts, ln in sorted(lines)]


PAYMENTS_V40 = {
    "service": {"name": "payments", "version": "v40"},
    "http": {"listen": "0.0.0.0:8080", "timeout_ms": 9000, "max_body_kb": 256},
    "db": {
        "host": "payments-db.internal:5432",
        "name": "payments",
        "pool": {"max_size": 50, "min_idle": 5, "acquire_timeout_ms": 10000},
    },
    "processor": {
        "endpoint": "https://psp.internal/v2",
        "retry": {"max_attempts": 2, "backoff_ms": 400},
    },
    "ledger": {"endpoint": "http://ledger.internal:8080", "idempotency_mode": "enforce"},
    "logging": {"level": "info", "format": "kv", "slow_charge_ms": 5000},
    "features": {"wallets": True, "partial_capture": False},
}


def payments_v41() -> dict:
    cfg = json.loads(json.dumps(PAYMENTS_V40))
    cfg["service"]["version"] = "v41"
    cfg["db"]["pool"]["max_size"] = 5
    cfg["ledger"]["idempotency_mode"] = "log_only"
    cfg["logging"]["level"] = "debug"
    return cfg


def to_yaml(obj: dict, indent: int = 0) -> str:
    out = []
    for k, v in obj.items():
        if isinstance(v, dict):
            out.append(f"{' ' * indent}{k}:")
            out.append(to_yaml(v, indent + 2))
        else:
            val = "true" if v is True else "false" if v is False else v
            out.append(f"{' ' * indent}{k}: {val}")
    return "\n".join(out)


def flat(obj: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in obj.items():
        key = f"{prefix}{k}"
        out.update(flat(v, key + ".") if isinstance(v, dict) else {key: v})
    return out


DEPLOYS = [
    (
        "D-2284",
        "inventory",
        "v12.3",
        t(9, 10) - timedelta(days=5),
        7,
        "a.mensah",
        "CHG-5488",
        "Batch SKU lookups for cart reservation",
    ),
    (
        "D-2286",
        "edge",
        "v7.1",
        t(15, 30) - timedelta(days=4),
        9,
        "s.quint",
        "CHG-5497",
        "TLS session cache size; access-log field order",
    ),
    (
        "D-2288",
        "checkout",
        "v33",
        t(11, 5) - timedelta(days=2),
        12,
        "j.alvarez",
        "CHG-5506",
        "Retry once on payment upstream timeout (was: fail fast)",
    ),
    (
        "D-2290",
        "inventory",
        "v12.4",
        t(11, 20),
        6,
        "a.mensah",
        "CHG-5514",
        "Fix reservation expiry off-by-one",
    ),
    (
        "D-2291",
        "payments",
        "v41",
        DEPLOY_START,
        None,
        "t.brandt",
        "CHG-5519",
        "Connection handling cleanup; quieter ledger client; debug logging for PSP calls",
    ),
    (
        "D-2293",
        "notifier",
        "v5.8",
        t(14, 2),
        4,
        "k.osei",
        "CHG-5520",
        "Email template tweaks for order confirmation",
    ),
    (
        "D-2295",
        "edge",
        "v7.1-cfg2",
        t(14, 33),
        2,
        "m.okafor",
        "CHG-5522",
        "Raise checkout upstream timeout alert threshold from 2% to 5% (temporary)",
    ),
    (
        "D-2297",
        "payments",
        "v40",
        ROLLBACK_START,
        None,
        "r.lindqvist",
        "CHG-5524",
        "Rollback payments to v40",
    ),
]


def deploy_history() -> list[dict]:
    out = []
    for did, svc, ver, start, mins, author, chg, summary in DEPLOYS:
        done = {"D-2291": DEPLOY_DONE, "D-2297": ROLLBACK_DONE}.get(did) or start + timedelta(
            minutes=mins
        )
        out.append(
            {
                "id": did,
                "service": svc,
                "version": ver,
                "started": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "completed": done.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "strategy": "rolling",
                "author": author,
                "change_ticket": chg,
                "summary": summary,
                "status": "succeeded",
            }
        )
    return out


# ── Answers ───────────────────────────────────────────────────────────────────────────────────


def minutes(a: datetime, b: datetime) -> int:
    return int((b - a).total_seconds() // 60)


def answers(orders, edge, checkout, pay_lines, captures, pool, history) -> dict:
    statuses: dict[str, int] = {}
    for ln in edge:
        s = ln.split("status=")[1].split()[0]
        statuses[s] = statuses.get(s, 0) + 1
    shown = [o for o in orders if o.start >= WINDOW_START]
    fails = sorted((o for o in shown if o.outcome == "timeout_fail"), key=lambda o: o.end)
    inv = [o for o in shown if o.outcome == "inventory_fail"]
    retried = [o for o in shown if o.outcome == "retry_ok"]
    first_504, last_504 = fails[0].end, fails[-1].end

    by_code: dict[str, int] = {}
    for ln in checkout:
        if " ERROR " in ln:
            code = ln.split("code=")[1].split()[0]
            by_code[code] = by_code.get(code, 0) + 1
    first_timeout = min(
        o.start + CLIENT_TIMEOUT for o in shown if o.outcome in ("retry_ok", "timeout_fail")
    )

    sat = [r for r in pool if r["in_use"] == r["max_size"]]
    late = sorted(ln.split("charge=")[1].split()[0] for ln in pay_lines if "client=gone" in ln)

    counts: dict[str, list[Capture]] = {}
    for c in captures:
        counts.setdefault(c.order.order, []).append(c)
    twice = sorted(o for o, cs in counts.items() if len(cs) > 1)
    overcharge = round(sum(counts[o][0].order.amount for o in twice), 2)
    failed_ids = {o.order for o in shown if o.outcome == "timeout_fail"}
    charged_failed = sorted(o for o in counts if o in failed_ids)

    v40, v41 = flat(PAYMENTS_V40), flat(payments_v41())
    changed = sorted(k for k in v40 if v40[k] != v41[k] and k != "service.version")
    trigger = next(d for d in history if d["id"] == "D-2291")
    trigger_done = datetime.strptime(trigger["completed"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)

    claims = {
        "C1": True,  # first 504 time as stated
        "C2": len(inv) > len(fails),
        "C3": True,  # number of orders charged twice as stated
        "C4": len(sat) > 45,
        "C5": trigger["change_ticket"] == "CHG-5521",
        "C6": last_504 < ROLLBACK_DONE,
        "C7": not charged_failed,
    }
    return {
        "stage_1": {
            "count_by_status": dict(sorted(statuses.items())),
            "checkout_5xx_by_status": {"502": len(inv), "504": len(fails)},
            "first_checkout_504": hms(first_504),
            "last_checkout_504": hms(last_504),
            "first_page_acked_by": "m.okafor",
            "payments_page_escalated_to": "r.lindqvist",
        },
        "stage_2": {
            "checkout_errors_by_code": dict(sorted(by_code.items())),
            "dominant_failing_upstream": "payments",
            "orders_succeeded_after_retry": len(retried),
            "escalations": None,  # filled by build() once tickets are chosen
        },
        "stage_3": {
            "pool_max_size_during_incident": 5,
            "saturated_from": sat[0]["minute"],
            "saturated_until": sat[-1]["minute"],
            "saturated_minutes": len(sat),
            "peak_waiters": max(r["waiters"] for r in pool),
            "peak_wait_ms": max(r["max_wait_ms"] for r in pool),
            "late_captures": late,
            "first_timeout_minutes_after_saturation": minutes(
                datetime.strptime(f"2026-09-14 {sat[0]['minute']}", "%Y-%m-%d %H:%M").replace(
                    tzinfo=UTC
                ),
                first_timeout,
            ),
        },
        "stage_4": {
            "orders_charged_twice": twice,
            "overcharge_total": overcharge,
            "failed_orders_charged": charged_failed,
            "first_capture_without_idempotency_key": None,  # from the ledger lines, in build()
            "last_capture_without_idempotency_key": None,
        },
        "stage_5": {
            "trigger_deploy": "D-2291",
            "trigger_completed_at": hms(trigger_done),
            "changed_settings": changed,
            "saturation_cause": "db.pool.max_size",
            "duplicate_cause": "ledger.idempotency_mode",
            "minutes_deploy_to_first_checkout_504": minutes(trigger_done, first_504),
            "rollback_deploy": "D-2297",
            "runbook_violations": ["db.pool.max_size", "ledger.idempotency_mode"],
        },
        "stage_6": {"claims": claims},
        "final": {
            "root_cause_service": "payments",
            "trigger_deploy": "D-2291",
            "root_cause_settings": ["db.pool.max_size", "ledger.idempotency_mode"],
            "checkout_504s": len(fails),
            "orders_charged_twice": len(twice),
            "failed_orders_charged": len(charged_failed),
            "customer_impact_window": [hms(first_504), hms(last_504)],
        },
        "_facts": {
            "first_504": first_504,
            "twice": twice,
            "fails": fails,
            "retried": retried,
            "inv": inv,
            "charged_failed": charged_failed,
            "sat": sat,
        },
    }


# ── Narrative artifacts ───────────────────────────────────────────────────────────────────────

README = """\
# Larkspur shop: incident workspace

Larkspur is a mid-sized web shop. A customer request enters through `edge` (two nodes) and
checkout calls three internal services in order:

    browser -> edge -> checkout -> inventory   (reserve stock)
                               -> payments    (authorize and capture the charge)
                                    -> payments-db (PostgreSQL, through a connection pool)
                                    -> ledger      (append-only money ledger)

- edge: TLS termination and routing. Access logs are sampled for background traffic but every
  `POST /api/checkout` is logged. A checkout that times out upstream returns 504; an upstream
  error returns 502.
- checkout: orchestrates an order. It gives payments 8 s per attempt. Since v33 it retries a
  timed-out payment once with a new charge id.
- payments: one charge id per attempt. A charge whose client has gone away may still complete.
  Every capture is posted to the ledger, normally with an idempotency key per order.
- ledger: one entry per money movement. Settlement batches close entries every 15 minutes.

All timestamps are UTC. The incident under review happened on 2026-09-14 between roughly
13:30 and 15:05.

Evidence is released into `evidence/` in stages; see your instructions.
"""

BRIEF_HEAD = """\
# Stage {n} brief: {title}

Released files: {files}

{body}

Record your answers in `/app/report/incident.json` under `"stage_{n}"`, using exactly the keys
below, plus a `notes` string (two to five sentences: what you found and how it changes the
working hypothesis). Times are `HH:MM:SS` (or `HH:MM` where stated), UTC, as they appear in the
evidence. Lists are sorted ascending. Counts are integers.

| Key | Type | Question |
|---|---|---|
{rows}
"""


def brief(n: int, title: str, files: list[str], body: str, rows: list[tuple[str, str, str]]) -> str:
    table = "\n".join(f"| `{k}` | {ty} | {q} |" for k, ty, q in rows)
    return BRIEF_HEAD.format(
        n=n, title=title, files=", ".join(f"`{f}`" for f in files), body=body, rows=table
    )


def pager_md() -> str:
    return """\
# Pager export, 2026-09-14 (UTC)

| Page | Opened | Alert | Severity | Routed to | Acknowledged | Resolved |
|---|---|---|---|---|---|---|
| PAGE-309 | 12:51:40 | inventory: reservation expiry job lagging > 10 min | low | inventory on-call (a.mensah) | 12:55:02 by a.mensah | 13:20:11 |
| PAGE-311 | 14:09:12 | edge: checkout 5xx ratio > 2% (5 min) | high | edge on-call (m.okafor) | 14:12:40 by m.okafor | 14:58:30 |
| PAGE-312 | 14:15:03 | payments: charge latency p99 > 5 s (5 min) | high | payments on-call primary (t.brandt) | not acknowledged | 14:57:44 |
| PAGE-312 | 14:30:03 | (escalation after 15 min without ack) | high | payments on-call secondary (r.lindqvist) | 14:31:10 by r.lindqvist | 14:57:44 |
| PAGE-313 | 14:22:40 | inventory: reserve error rate > 1% (5 min) | low | inventory on-call (a.mensah) | auto-resolved | 14:24:40 |
| PAGE-314 | 14:36:15 | edge: checkout 5xx ratio > 5% (5 min) | high | edge on-call (m.okafor) | 14:36:52 by m.okafor | 14:58:30 |

## Responder chat excerpts

- 14:13:05 m.okafor: edge looks healthy itself, the 5xx are all on POST /api/checkout. Pulling
  the access log. Not paging checkout yet.
- 14:24:51 m.okafor: inventory page auto-resolved, probably unrelated, saw one 502 earlier too.
- 14:33:20 m.okafor: raising the edge alert threshold to 5% for now so the pager stops flapping
  while we look (D-2295). This does not change traffic.
- 14:31:40 r.lindqvist: picking up payments. Charge latency is through the roof, looking at the
  pool metrics.
- 14:46:02 r.lindqvist: going to roll payments back to v40, details in the deploy log.
- 14:58:30 m.okafor: checkout ratio back under 1% for five minutes. Resolving edge pages.
"""


def escalations_md(facts: dict, g: Gen) -> tuple[str, dict]:
    fails, retried, inv = facts["fails"], facts["retried"], facts["inv"]
    twice = set(facts["twice"])
    charged_failed = set(facts["charged_failed"])
    plain_fail = next(o for o in fails[2:] if o.order not in charged_failed)
    double = next(o for o in retried if o.order in twice)
    inv_mid = next(o for o in inv if INCIDENT[0] <= o.start < INCIDENT[1])
    failed_charged = next(o for o in fails if o.order in charged_failed)
    tickets = [
        (
            "TCK-8801",
            plain_fail,
            'Tried to pay for my order and got a "gateway timeout" page after a long spinner. '
            "Order {o} never showed up in my account.",
        ),
        (
            "TCK-8806",
            double,
            "My bank shows two charges for order {o}, same amount, a few seconds apart. "
            "The site said the order went through.",
        ),
        (
            "TCK-8810",
            inv_mid,
            'Checkout failed instantly with "something went wrong" for order {o}. '
            "Worked when I tried again later.",
        ),
        (
            "TCK-8815",
            failed_charged,
            "Got an error at checkout for order {o} so I assumed nothing happened, "
            "but the money left my account. No order confirmation.",
        ),
    ]
    want = {
        "TCK-8801": "failed:payments",
        "TCK-8806": "succeeded_after_retry",
        "TCK-8810": "failed:inventory",
        "TCK-8815": "failed:payments",
    }
    parts = ["# Customer escalations received 2026-09-14 (support tier 2)", ""]
    for tid, o, text in tickets:
        when = o.start - timedelta(minutes=g.rng.randint(0, 3))
        parts += [
            f"## {tid}",
            "",
            f"- Received: 2026-09-14 {hms(o.end + timedelta(minutes=g.rng.randint(25, 70)))} UTC",
            f"- Customer says they tried at about {hm(when)} UTC",
            f"- Amount quoted by customer: {o.amount:.2f}",
            "",
            "> " + text.format(o=o.order),
            "",
        ]
    return "\n".join(parts), want


def runbook_md() -> str:
    return """\
# Runbook: payments service

## Production configuration rules

These are checked in review; a deploy that violates one needs a written exception.

1. `db.pool.max_size` must be at least 40 in production. At peak, checkout produces about 25
   concurrent charges and each holds a connection for the whole authorize + capture.
2. `db.pool.acquire_timeout_ms` must not exceed `http.timeout_ms` + 2000.
3. `ledger.idempotency_mode` must be `enforce` in production. `log_only` records a duplicate
   key and accepts the entry anyway; it exists for ledger replays in staging.
4. `processor.retry.max_attempts` must be at most 3.
5. `logging.level` may be `debug` for at most 24 hours and needs no exception.

## Symptoms

- Charge latency p99 above 5 s with flat processor latency usually means pool waits. Check
  `pool.csv` (one row per minute: connections in use, pool size, waiters, worst wait).
- `status=abandoned reason=pool_wait_exceeded` means the charge never reached the processor.
- `client=gone` on a capture means checkout had already given up on that attempt.

## Rollback

Roll back with the deploy tool (`deployctl rollback payments --to <version>`). A rolling
rollback replaces one pod at a time; the pool size applies per pod as it restarts.
"""


def postmortem_md(facts: dict, pool: list[dict]) -> str:
    return f"""\
# DRAFT postmortem: checkout outage 2026-09-14

Author: j.alvarez (checkout team). Status: draft, not reviewed.

## Summary

Between {hm(facts["first_504"])} and about 14:55 UTC, checkout failed for a large share of
customers. Payments latency rose sharply after a routine deploy and checkout requests timed
out. The service recovered after payments was rolled back.

## Claims to verify before review

- **C1.** The first checkout 504 reached a customer at {hms(facts["first_504"])}.
- **C2.** Inventory errors caused most of the failed checkouts in the edge log; payments
  timeouts were a secondary effect.
- **C3.** {len(facts["twice"])} orders were charged twice.
- **C4.** The payments connection pool was saturated for more than 45 minutes.
- **C5.** D-2291 was approved under change ticket CHG-5521.
- **C6.** No checkout 504 occurred after the rollback (D-2297) completed.
- **C7.** Orders whose checkout failed were never charged, so no refunds are needed for them.

## Proposed actions (not part of this review)

1. Alert on pool waiters, not only on latency.
2. Make checkout reuse the charge id when it retries.
3. Block deploys that violate the runbook configuration rules.

## Timeline (incomplete)

- 13:41 D-2291 starts rolling out.
- {hm(facts["first_504"])} first customer-facing errors.
- 14:09 first page (edge).
- 14:47 rollback starts.
"""


# ── Build ─────────────────────────────────────────────────────────────────────────────────────


def build() -> dict[Path, str]:
    g = Gen()
    orders = build_orders(g)
    pay_lines, captures = payments_events(g, orders)
    pool = pool_rows(g)
    edge = edge_log(g, orders)
    checkout = checkout_log(g, orders)
    ledger = ledger_log(g, captures)
    history = deploy_history()
    ans = answers(orders, edge, checkout, pay_lines, captures, pool, history)
    facts = ans.pop("_facts")
    esc_text, esc = escalations_md(facts, g)
    ans["stage_2"]["escalations"] = esc
    none_lines = [ln for ln in ledger if "type=CAPTURE" in ln and "idem=none" in ln]
    ans["stage_4"]["first_capture_without_idempotency_key"] = none_lines[0][11:19]
    ans["stage_4"]["last_capture_without_idempotency_key"] = none_lines[-1][11:19]

    pool_csv = "minute,in_use,max_size,waiters,max_wait_ms\n" + "".join(
        f"{r['minute']},{r['in_use']},{r['max_size']},{r['waiters']},{r['max_wait_ms']}\n"
        for r in pool
    )
    ev = "evidence/stage_{}/{}"
    stages = {
        1: {
            "edge/access.log": "\n".join(edge) + "\n",
            "pager.md": pager_md(),
        },
        2: {
            "checkout/app.log": "\n".join(checkout) + "\n",
            "escalations.md": esc_text,
        },
        3: {
            "payments/charges.log": "\n".join(pay_lines) + "\n",
            "payments/pool.csv": pool_csv,
        },
        4: {
            "ledger/entries.log": "\n".join(ledger) + "\n",
            "ledger/FORMAT.md": LEDGER_FORMAT,
        },
        5: {
            "deploys/history.json": json.dumps(history, indent=2) + "\n",
            "config/payments-v40.yaml": to_yaml(PAYMENTS_V40) + "\n",
            "config/payments-v41.yaml": to_yaml(payments_v41()) + "\n",
            "runbooks/payments.md": runbook_md(),
        },
        6: {
            "review/draft-postmortem.md": postmortem_md(facts, pool),
        },
    }
    briefs = {
        1: (
            "Edge view and paging",
            "Start with the customer-facing symptoms.",
            [
                (
                    "count_by_status",
                    "object",
                    "Every HTTP status in the edge access log mapped to its line count (keys are the status codes as strings).",
                ),
                (
                    "checkout_5xx_by_status",
                    "object",
                    "Counts of 5xx responses on `POST /api/checkout`, keyed by status code.",
                ),
                (
                    "first_checkout_504",
                    "HH:MM:SS",
                    "Timestamp of the first 504 on `POST /api/checkout`.",
                ),
                (
                    "last_checkout_504",
                    "HH:MM:SS",
                    "Timestamp of the last 504 on `POST /api/checkout`.",
                ),
                (
                    "first_page_acked_by",
                    "string",
                    "Who acknowledged the first high-severity page of the incident.",
                ),
                ("payments_page_escalated_to", "string", "Who the payments page escalated to."),
            ],
        ),
        2: (
            "Checkout service",
            "Explain the edge 5xx from checkout's side, and answer the escalations.",
            [
                (
                    "checkout_errors_by_code",
                    "object",
                    "Count of checkout `ERROR` lines per `code`.",
                ),
                (
                    "dominant_failing_upstream",
                    "string",
                    "The upstream service behind most failed checkouts.",
                ),
                (
                    "orders_succeeded_after_retry",
                    "integer",
                    "Orders whose payment timed out on attempt 1 but succeeded on attempt 2.",
                ),
                (
                    "escalations",
                    "object",
                    "For each ticket id: `failed:payments`, `failed:inventory`, `succeeded_after_retry` or `succeeded`, from what checkout actually did with that order (match the order id).",
                ),
            ],
        ),
        3: (
            "Payments and its database pool",
            "Test the hypothesis that payments, not checkout, is the bottleneck. `charges.log` is an excerpt: only charges that were slow (over 5 s), retried or not captured. You need your stage 2 findings for the last question.",
            [
                (
                    "pool_max_size_during_incident",
                    "integer",
                    "Pool `max_size` while checkout was failing.",
                ),
                (
                    "saturated_from",
                    "HH:MM",
                    "First minute in `pool.csv` where `in_use` equals `max_size`.",
                ),
                ("saturated_until", "HH:MM", "Last such minute."),
                (
                    "saturated_minutes",
                    "integer",
                    "Number of rows where `in_use` equals `max_size`.",
                ),
                ("peak_waiters", "integer", "Highest `waiters`."),
                ("peak_wait_ms", "integer", "Highest `max_wait_ms`."),
                (
                    "late_captures",
                    "list of strings",
                    "Charge ids captured after checkout had given up on them.",
                ),
                (
                    "first_timeout_minutes_after_saturation",
                    "integer",
                    "Whole minutes (rounded down) from the start of `saturated_from` to the first checkout `PAYMENT_UPSTREAM_TIMEOUT`.",
                ),
            ],
        ),
        4: (
            "Money movement",
            "Find out who was charged what. You need stages 1 to 3 to tell failed orders from successful ones.",
            [
                (
                    "orders_charged_twice",
                    "list of strings",
                    "Order ids with more than one `CAPTURE` entry.",
                ),
                (
                    "overcharge_total",
                    "number",
                    "Total amount captured beyond one capture per order, for those orders (2 decimals).",
                ),
                (
                    "failed_orders_charged",
                    "list of strings",
                    "Order ids whose checkout failed (504) but which have a `CAPTURE`.",
                ),
                (
                    "first_capture_without_idempotency_key",
                    "HH:MM:SS",
                    "Timestamp of the first `CAPTURE` with `idem=none`.",
                ),
                ("last_capture_without_idempotency_key", "HH:MM:SS", "Timestamp of the last one."),
            ],
        ),
        5: (
            "Change history and configuration",
            "Find the change behind everything so far.",
            [
                ("trigger_deploy", "string", "Deploy id that caused the incident."),
                ("trigger_completed_at", "HH:MM:SS", "When that deploy completed."),
                (
                    "changed_settings",
                    "list of strings",
                    "Dotted keys (`db.pool.max_size` style) whose value differs between payments v40 and v41, excluding `service.version`.",
                ),
                ("saturation_cause", "string", "The dotted key that explains the pool saturation."),
                (
                    "duplicate_cause",
                    "string",
                    "The dotted key that explains why the ledger accepted duplicate captures.",
                ),
                (
                    "minutes_deploy_to_first_checkout_504",
                    "integer",
                    "Whole minutes (rounded down) from the trigger deploy completing to the first checkout 504.",
                ),
                ("rollback_deploy", "string", "Deploy id of the rollback."),
                (
                    "runbook_violations",
                    "list of strings",
                    "Dotted keys whose v41 value breaks a runbook configuration rule.",
                ),
            ],
        ),
        6: (
            "Review and final report",
            "Check a colleague's draft against everything you have found, re-reading earlier evidence where needed, then finalize. Besides `stage_6`, this stage fills the top-level `final` object (keys in the second table below).",
            [
                (
                    "claims",
                    "object",
                    "For each claim id `C1`..`C7` in the draft: `true` if the evidence supports it as written, else `false`.",
                ),
            ],
        ),
    }
    final_rows = [
        ("root_cause_service", "string", "Service whose change caused the incident."),
        ("trigger_deploy", "string", "Deploy id."),
        (
            "root_cause_settings",
            "list of strings",
            "Dotted keys of the settings that caused the customer impact.",
        ),
        ("checkout_504s", "integer", "Checkout 504s in the edge log."),
        ("orders_charged_twice", "integer", "Number of orders charged twice."),
        ("failed_orders_charged", "integer", "Number of failed orders that were charged."),
        ("customer_impact_window", "list of 2 strings", "First and last checkout 504, `HH:MM:SS`."),
    ]

    files: dict[Path, str] = {HERE / "environment/workspace/README.md": README}
    for n, items in stages.items():
        title, body, rows = briefs[n]
        text = brief(n, title, sorted(items), body, rows)
        if n == 6:
            text += (
                "\n## `final` (top-level key)\n\n| Key | Type | Question |\n|---|---|---|\n"
                + "\n".join(f"| `{k}` | {ty} | {q} |" for k, ty, q in final_rows)
                + "\n"
            )
        items = {"BRIEF.md": text, **items}
        for name, content in items.items():
            files[HERE / "stages" / f"stage_{n}" / name] = content

    evidence = {
        ev.format(n, name): hashlib.sha256(
            files[HERE / "stages" / f"stage_{n}" / name].encode()
        ).hexdigest()
        for n in stages
        for name in ["BRIEF.md", *stages[n]]
    }
    expected = {"answers": ans, "evidence_sha256": dict(sorted(evidence.items()))}
    files[HERE / "tests/expected.json"] = json.dumps(expected, indent=2) + "\n"
    reference = {
        k: {**v, "notes": "Reference answer."} if k.startswith("stage_") else v
        for k, v in ans.items()
    }
    files[HERE / "solution/incident.json"] = json.dumps(reference, indent=2) + "\n"
    return files


LEDGER_FORMAT = """\
# ledger/entries.log format

One line per ledger event, UTC.

- `type=CAPTURE`: money taken from the customer for `order`, via payments `charge`.
- `type=REFUND`: money returned (negative amount), usually issued by support.
- `settlement`: a batch close; not a money movement.
- `idem`: the idempotency key payments sent with the entry. With `idempotency_mode=enforce`
  the ledger rejects a second capture for the same order key; with `log_only` it accepts it
  and only logs a warning on its side (not in this export). `none` means no key was sent.
- `src`: the payments pod (or support tool) that posted the entry.
"""


def main() -> None:
    for path, content in build().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))


if __name__ == "__main__":
    main()
