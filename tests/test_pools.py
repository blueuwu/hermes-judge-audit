"""Per-pool reporting rules and the judge seal for Phase 1b, on synthetic rows only."""

from __future__ import annotations

import json
import subprocess
from dataclasses import fields
from pathlib import Path

import pytest

from hjr import cli, pools, regrade, stats
from hjr.audit import HELDOUT_TAG
from hjr.pools import Boundary as R

SECRET = "SECRET-JUDGE-REASON"


def pool(
    not_done_tasks: int, zero_tasks: int = 0, split: str = "dev", n: int = 4, prefix: str = ""
) -> list[R]:
    """Each not-done task has one not-done boundary among n; zero tasks have none. The judge
    calls the not-done boundary done on even tasks, and every done boundary done."""
    rows = []
    for t in range(not_done_tasks):
        task = f"{prefix}nd{t}"
        rows += [R(f"{task}/0", task, split, "not_done", "done" if t % 2 == 0 else "continue")]
        rows += [R(f"{task}/{i}", task, split, "done", "done") for i in range(1, n)]
    for t in range(zero_tasks):
        task = f"{prefix}z{t}"
        rows += [R(f"{task}/{i}", task, split, "done", "done") for i in range(n)]
    return rows


def not_done_rate(name, rows, **kw):
    return pools.figure(
        name,
        rows,
        "not-done rate",
        lambda r: r.truth == "not_done",
        kind="truth",
        event="a not-done boundary",
        seed="s",
        **kw,
    )


def judge_done_given_not_done(name, rows, **kw):
    return pools.figure(
        name,
        rows,
        "judge done given not done",
        lambda r: r.judge == "done",
        kind="judge",
        event="a not-done boundary the judge called done",
        given=lambda r: r.truth == "not_done",
        seed="s",
        **kw,
    )


@pytest.fixture
def sealed(monkeypatch):
    monkeypatch.setattr(pools, "judge_unsealed", lambda root=None, head="HEAD": False)


@pytest.fixture
def unsealed(monkeypatch):
    monkeypatch.setattr(pools, "judge_unsealed", lambda root=None, head="HEAD": True)


# ── Seal on a real temporary repository ───────────────────────────────


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "commit", "-q", "--allow-empty", "-m", "base")
    return root


def test_judge_metric_on_heldout_refused_without_the_tag(repo):
    assert not pools.judge_unsealed(repo)
    with pytest.raises(PermissionError, match=HELDOUT_TAG):
        judge_done_given_not_done("heldout", pool(5, split="heldout"), root=repo)
    with pytest.raises(PermissionError):
        judge_done_given_not_done("all", pool(5) + pool(1, split="heldout", prefix="h"), root=repo)


def test_judge_metric_on_heldout_refused_when_the_tag_is_off_head(repo):
    _git(repo, "checkout", "-q", "-b", "elsewhere")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "side")
    _git(repo, "tag", HELDOUT_TAG)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "analysis")
    assert _git(repo, "tag", "--list", HELDOUT_TAG) == HELDOUT_TAG
    assert not pools.judge_unsealed(repo)
    with pytest.raises(PermissionError, match="ancestor of HEAD"):
        judge_done_given_not_done("heldout", pool(5, split="heldout"), root=repo)


def test_judge_metric_on_heldout_allowed_when_the_tag_is_an_ancestor(repo):
    _git(repo, "tag", "-a", HELDOUT_TAG, "-m", "freeze")  # annotated: peeled to its commit
    assert pools.judge_unsealed(repo)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "analysis")
    assert pools.judge_unsealed(repo)
    f = judge_done_given_not_done("heldout", pool(5, split="heldout"), root=repo)
    assert f.micro is not None and f.micro.estimate == pytest.approx(3 / 5)


def test_truth_metric_on_heldout_allowed_while_sealed(repo):
    assert not pools.judge_unsealed(repo)
    f = not_done_rate("Stage A", pool(5, zero_tasks=11, split="heldout"), root=repo)
    assert f.micro.estimate == pytest.approx(5 / 64)


def test_dev_only_judge_pool_needs_no_tag(repo):
    f = judge_done_given_not_done("dev", pool(5), root=repo)
    assert f.micro is not None


# ── Gate, clusters and intervals ──────────────────────────────────────


def test_not_done_rate_clusters_include_zero_not_done_tasks(sealed):
    # Stage A shape: 16 task clusters, 5 with a not-done boundary
    rows = pool(5, zero_tasks=11, split="heldout")
    f = not_done_rate("Stage A", rows)
    assert (f.n_clusters, f.n_clusters_with_events, f.not_done_tasks) == (16, 5, 5)
    assert not f.counts_only and not f.micro.coarse
    assert f.micro.estimate == pytest.approx(5 / 64)
    assert f.macro.estimate == pytest.approx(5 / 16 * 0.25)
    ref = stats.task_macro_bootstrap(
        rows,
        lambda r: r.task_id,
        lambda r: float(r.truth == "not_done"),
        seed="s:Stage A:not-done rate:macro",
    )
    assert (f.macro.estimate, f.macro.low, f.macro.high) == (ref.estimate, ref.low, ref.high)


def test_every_interval_states_clusters_and_clusters_with_events(unsealed):
    names = {x.name for x in fields(pools.PoolCI)}
    assert {"n_clusters", "n_clusters_with_events"} <= names
    rows = pool(6, zero_tasks=4)
    figures = [
        not_done_rate("dev", rows),
        *pools.judge_figures("dev", rows, seed="s"),
    ]
    for f in figures:
        for ci in (f.micro, f.macro):
            assert ci is not None
            assert (ci.n_clusters, ci.n_clusters_with_events) == (
                f.n_clusters,
                f.n_clusters_with_events,
            )
        text = "\n".join(pools.render(f))
        assert "| n_clusters | n_clusters_with_events |" in text
        assert f"n_clusters={f.n_clusters}, n_clusters_with_events=" in text
    rate, done_nd, notdone_d = figures
    assert (rate.micro.n_clusters, rate.micro.n_clusters_with_events) == (10, 6)
    # Judge done on the not-done boundary of tasks 0, 2, 4: 3 of the 6 contributing tasks
    assert (done_nd.micro.n_clusters, done_nd.micro.n_clusters_with_events) == (6, 3)
    # Done boundaries are always called done: no events, in all 10 contributing tasks
    assert (notdone_d.micro.n_clusters, notdone_d.micro.n_clusters_with_events) == (10, 0)


def test_five_clusters_pass_but_are_coarse_with_the_count_stated(sealed):
    f = not_done_rate("A+B selected, dev", pool(5))
    assert f.n_clusters == 5 and not f.counts_only and f.micro.coarse and f.macro.coarse
    assert "coarse, n_clusters=5, n_clusters_with_events=5" in "\n".join(pools.render(f))
    wide = not_done_rate("wide", pool(5, zero_tasks=6))
    assert wide.n_clusters == 11 and not wide.micro.coarse


def test_fewer_than_five_tasks_emit_only_per_task_counts_for_truth(sealed):
    f = not_done_rate("dev", pool(4, zero_tasks=3))
    assert f.not_done_tasks == 4 and f.counts_only
    assert f.micro is None and f.macro is None
    assert pools.TaskCount("nd0", 1, 4) in f.per_task and pools.TaskCount("z0", 0, 4) in f.per_task
    text = "\n".join(pools.render(f))
    assert "per-task counts only" in text
    for banned in ("Micro", "Task-macro", "Rate", "0.25", "4/28", "%"):
        assert banned not in text


def test_fewer_than_five_tasks_give_no_judge_rate_estimate_or_interval(unsealed):
    rows = pool(2, zero_tasks=5)
    for f in pools.judge_figures("dev", rows, seed="s"):
        assert f.counts_only and f.micro is None and f.macro is None
        text = "\n".join(pools.render(f))
        assert "| Task | Events | Boundaries |" in text
        for banned in ("Micro", "Task-macro", "Rate", "95%", "0.5", "["):
            assert banned not in text
    table = pools.contingency(rows)
    assert table["nd0"][("not_done", "done")] == 1 and table["nd1"][("not_done", "continue")] == 1
    assert table["z0"][("done", "done")] == 4


def test_gate_applies_to_each_pool_separately(sealed):
    dev = pool(3)
    heldout = pool(3, split="heldout", prefix="h")
    assert not not_done_rate("all", dev + heldout).counts_only
    assert not_done_rate("dev", dev).counts_only
    assert not_done_rate("heldout", heldout).counts_only


def test_per_task_only_figure_has_rates_but_no_pooled_estimate(sealed):
    f = not_done_rate("Stage B", pool(5, split="heldout"), pooled=False)
    assert f.micro is None and f.macro is None and not f.counts_only
    text = "\n".join(pools.render(f))
    assert "| nd0 | 1 | 4 | 0.2500 |" in text and "Micro" not in text


def test_figures_are_seeded_and_deterministic(sealed):
    rows = pool(7, zero_tasks=2)
    assert not_done_rate("dev", rows) == not_done_rate("dev", rows)


# ── Loading and the CLI on synthetic files ────────────────────────────


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    """Synthetic Stage A (6 tasks, 5 with a not-done) and Stage B (the 5 selected tasks)."""
    monkeypatch.setattr(regrade, "TRUTH", tmp_path / "truth")
    (tmp_path / "truth").mkdir()
    (tmp_path / "frozen").mkdir()
    split = {"d1": "dev", "d2": "dev", "h1": "heldout", "h2": "heldout", "h3": "heldout"}
    split["z1"] = "heldout"

    def write(stem, rows, excluded):
        docs, truth = [], []
        for i, (task, state, verdict) in enumerate(rows):
            bid = f"{stem}/hjr-{task}__t{i}/b01"
            docs.append(
                {
                    "boundary_id": bid,
                    "task_id": f"hjr/{task}",
                    "split": split[task],
                    "phase": "1b-enrichment",
                    "controller_verdict": verdict
                    and {"verdict": verdict, "reason": SECRET, "judge": "j"},
                }
            )
            truth.append({"boundary_id": bid, "truth_state": state, "requirements": {}})
        path = tmp_path / "frozen" / f"{stem}.jsonl"
        path.write_text("".join(json.dumps(d) + "\n" for d in docs), encoding="utf-8")
        (tmp_path / "truth" / f"{stem}.jsonl").write_text(
            "".join(json.dumps(t) + "\n" for t in truth), encoding="utf-8"
        )
        path.with_name(f"{stem}.excluded.json").write_text(json.dumps(excluded), encoding="utf-8")
        return path

    a_rows = [(t, "not_done", "done") for t in ("d1", "d2", "h1", "h2", "h3")]
    a_rows += [(t, "done", "done") for t in split for _ in range(3)]
    b_rows = [("d1", "not_done", "wait"), ("d1", "done", None), ("d2", "done", "continue")]
    b_rows += [(t, "not_done", "done") for t in ("d2", "h1", "h2", "h3")]
    a = write("s-a", a_rows, [{"trial": "z1__x", "reason": pools.NO_BOUNDARY[0]}])
    b = write("s-b", b_rows, [{"trial": "d1__y", "reason": pools.NO_BOUNDARY[0]}])
    return a, b


def test_loader_reads_judge_labels_only_for_an_open_pool(frozen, sealed):
    a, _ = frozen
    rows = pools.load(a)
    assert all(r.judge is None for r in rows) and {r.split for r in rows} == {"dev", "heldout"}
    with pytest.raises(PermissionError):
        pools.load(a, judge=True)
    dev = pools.load(a, splits={"dev"}, judge=True)
    assert {r.judge for r in dev} == {"done"} and SECRET not in repr(dev)
    with pytest.raises(ValueError, match="phase 1a"):
        pools.load(a, phase="1a")


def test_cli_refuses_a_sealed_judge_pool_and_writes_nothing(frozen, sealed, tmp_path, capsys):
    a, b = frozen
    out = tmp_path / "report.md"
    for pool_name in ("heldout", "all"):
        argv = ["phase1b-pools", "--stage-a", str(a), "--stage-b", str(b)]
        argv += ["--judge-pool", "dev", "--judge-pool", pool_name, "--out", str(out)]
        assert cli.main(argv) == 2
        assert not out.exists()
        assert "refused:" in capsys.readouterr().out


def test_cli_report_on_synthetic_files(frozen, sealed, tmp_path):
    a, b = frozen
    out = tmp_path / "report.md"
    argv = ["phase1b-pools", "--stage-a", str(a), "--stage-b", str(b), "--out", str(out)]
    assert cli.main(argv) == 0
    text = out.read_text(encoding="utf-8")
    assert SECRET not in text
    stage_a, rest = text.split("## Stage B", 1)
    stage_b, judge = rest.split("## Stage A+B, selected tasks, dev", 1)
    # Stage A: pooled with 6 clusters, all held-out truth included while the judge is sealed
    assert "coarse, n_clusters=6, n_clusters_with_events=5" in stage_a
    assert "| hjr/z1 | 1 | 0 |" in stage_a and "| hjr/d1 | 1 | 4 |" in stage_a
    assert "| Rate |" not in stage_a
    # Stage B: per task, no pooled estimate, the no-boundary trial kept out of the rate
    assert "Micro" not in stage_b and "| hjr/d1 | 1 | 2 | 0.5000 |" in stage_b
    assert "not prevalence" in stage_b and "| hjr/d1 | 1 | 0 |" in stage_b
    # Dev judge pool: 2 not-done tasks, so contingency counts only
    assert "Distinct tasks with a primary not-done boundary: 2." in judge
    assert "fails the reporting rule" in judge
    for banned in ("Micro", "Task-macro", "Rate", "95%", "0."):
        assert banned not in judge
    assert "| hjr/d1 | not_done | 2 | 1 | 1 | 0 | 0 |" in judge
    assert "| hjr/d1 | done | 4 | 3 | 0 | 0 | 1 |" in judge
    assert "| hjr/d2 | not_done | 2 | 2 | 0 | 0 | 0 |" in judge
    assert "| hjr/d2 | done | 4 | 3 | 1 | 0 | 0 |" in judge
    assert "hjr/h1" not in judge
