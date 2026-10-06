"""Per-pool reporting rules for Phase 1b, on synthetic rows only."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from hjr import audit, pools, stats


@dataclass(frozen=True)
class R:
    task_id: str
    split: str
    truth: str
    done: bool = False  # the judge's item decision


def pool(not_done_tasks: int, zero_tasks: int = 0, split: str = "dev", n: int = 4) -> list[R]:
    """Each not-done task has one not-done boundary among n; zero tasks have none."""
    rows = []
    for t in range(not_done_tasks):
        rows += [R(f"nd{t}", split, "not_done", done=t % 2 == 0)]
        rows += [R(f"nd{t}", split, "done", done=True) for _ in range(n - 1)]
    for t in range(zero_tasks):
        rows += [R(f"z{t}", split, "done", done=True) for _ in range(n)]
    return rows


def not_done_rate(name, rows):
    return pools.figure(name, rows, "not-done rate", lambda r: r.truth == "not_done", seed="s")


@pytest.fixture
def sealed(monkeypatch):
    monkeypatch.setattr(audit, "heldout_unlocked", lambda: False)


@pytest.fixture
def unsealed(monkeypatch):
    monkeypatch.setattr(audit, "heldout_unlocked", lambda: True)


def test_fewer_than_five_not_done_tasks_reports_counts_only(sealed):
    f = not_done_rate("dev", pool(4, zero_tasks=3))
    assert f.not_done_tasks == 4 and f.counts_only and not f.coarse
    assert f.micro is None and f.macro is None
    assert (f.k, f.n, f.clusters) == (4, 28, 7)
    assert ("nd0", 1, 4) in f.per_task and ("z0", 0, 4) in f.per_task
    text = "\n".join(pools.render(f))
    assert "per-task counts only" in text and "Micro" not in text


def test_not_done_rate_clusters_include_zero_not_done_tasks(unsealed):
    # Stage A shape: 16 task clusters, 5 with a not-done boundary
    rows = pool(5, zero_tasks=11, split="heldout")
    f = not_done_rate("Stage A", rows)
    assert (f.clusters, f.not_done_tasks) == (16, 5)
    assert not f.counts_only and not f.coarse
    assert f.micro.estimate == pytest.approx(5 / 64)
    assert f.macro.estimate == pytest.approx(5 / 16 * 0.25)
    assert f.macro == stats.task_macro_bootstrap(
        rows,
        lambda r: r.task_id,
        lambda r: float(r.truth == "not_done"),
        seed="s:Stage A:not-done rate:macro",
    )


def test_five_clusters_pass_but_are_coarse_with_the_count_stated(sealed):
    f = not_done_rate("A+B selected, dev", pool(5))
    assert f.clusters == 5 and not f.counts_only and f.coarse
    assert "coarse: 5 task clusters" in "\n".join(pools.render(f))
    wide = not_done_rate("wide", pool(5, zero_tasks=6))
    assert wide.clusters == 11 and not wide.coarse


def test_judge_metric_clusters_over_contributing_tasks_and_gates_on_the_pool(sealed):
    rows = pool(6, zero_tasks=4)
    f = pools.figure(
        "dev",
        rows,
        "DONE given not_done",
        lambda r: r.done,
        given=lambda r: r.truth == "not_done",
        seed="s",
    )
    assert (f.n, f.clusters, f.not_done_tasks) == (6, 6, 6)
    assert f.k == 3 and f.micro.estimate == 0.5 and f.macro.estimate == 0.5
    # Not DONE given done: zero-not-done tasks contribute, and the gate is still the pool's
    fc = pools.figure(
        "dev",
        rows,
        "not DONE given done",
        lambda r: not r.done,
        given=lambda r: r.truth == "done",
        seed="s",
    )
    assert (fc.clusters, fc.not_done_tasks, fc.k) == (10, 6, 0)


def test_gate_applies_to_each_pool_separately(unsealed):
    dev = pool(3)
    heldout = [R(r.task_id.replace("nd", "h"), "heldout", r.truth, r.done) for r in pool(3)]
    assert not_done_rate("all", dev + heldout).counts_only is False
    assert not_done_rate("dev", dev).counts_only
    assert not_done_rate("heldout", heldout).counts_only


def test_heldout_rows_are_sealed_until_repair_freeze(sealed):
    with pytest.raises(PermissionError, match="repair-freeze-v1"):
        not_done_rate("all", pool(5) + [R("h", "heldout", "done")])
    with pytest.raises(PermissionError):
        not_done_rate("heldout", pool(5, split="heldout"))
    assert not_done_rate("dev", pool(5)).micro is not None


def test_figures_are_seeded_and_deterministic(sealed):
    rows = pool(7, zero_tasks=2)
    assert not_done_rate("dev", rows) == not_done_rate("dev", rows)
    other = pools.figure("dev", rows, "not-done rate", lambda r: r.truth == "not_done", seed="t")
    assert other.micro.estimate == not_done_rate("dev", rows).micro.estimate
