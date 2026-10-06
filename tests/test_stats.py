from __future__ import annotations

import pytest

from hjr import stats


def test_wilson_matches_reference_values():
    lo, hi = stats.wilson(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-4) and hi == pytest.approx(0.7634, abs=1e-4)
    lo, hi = stats.wilson(0, 20)
    assert lo == 0.0 and hi == pytest.approx(0.1611, abs=1e-4)
    assert stats.wilson(0, 0) is None


def test_mcnemar_counts_discordant_pairs_and_flags_low_power():
    first = [True] * 6 + [False] * 4 + [True, False]
    second = [False] * 6 + [False] * 4 + [True, False]
    m = stats.mcnemar_exact(first, second)
    assert (m.b, m.c, m.discordant) == (6, 0, 6)
    assert m.p == pytest.approx(0.03125)
    assert not m.detectable
    assert stats.mcnemar_exact([True], [True]).p is None
    with pytest.raises(ValueError):
        stats.mcnemar_exact([True], [])


def test_holm_steps_down_and_keeps_order():
    adj = stats.holm({"a": 0.01, "b": 0.04, "c": 0.03, "d": None})
    assert adj["a"] == pytest.approx(0.03)
    assert adj["c"] == pytest.approx(0.06)
    assert adj["b"] == pytest.approx(0.06)  # monotone: never below the previous step
    assert adj["d"] is None


def test_agreement_kappa_prevalence_and_pabak():
    pairs = [("done", "done")] * 8 + [("not_done", "not_done")] * 1 + [("done", "not_done")]
    a = stats.agreement(pairs, ["done", "not_done"])
    assert a.observed == pytest.approx(0.9)
    # pe = 0.9*0.8 + 0.1*0.2 = 0.74
    assert a.kappa == pytest.approx((0.9 - 0.74) / 0.26)
    assert a.pabak == pytest.approx(0.8)
    assert a.prevalence["done"] == pytest.approx(0.85)
    assert stats.agreement([], ["x"]).kappa is None


def test_cluster_bootstrap_resamples_whole_tasks_and_is_seeded():
    rows = [("t1", 1)] * 5 + [("t2", 0)] * 5 + [("t3", 1)] * 2

    def mean(rs):
        return sum(v for _, v in rs) / len(rs) if rs else None

    a = stats.cluster_bootstrap(rows, lambda r: r[0], mean, seed="s", resamples=500)
    b = stats.cluster_bootstrap(rows, lambda r: r[0], mean, seed="s", resamples=500)
    assert a == b
    assert a.estimate == pytest.approx(7 / 12)
    assert 0.0 <= a.low <= a.estimate <= a.high <= 1.0
    # With one task per value, the interval spans whole-task outcomes
    one = stats.cluster_bootstrap([("t", 1)], lambda r: r[0], mean, seed=1, resamples=50)
    assert (one.low, one.high) == (1.0, 1.0)


def test_cluster_bootstrap_counts_undefined_resamples():
    rows = [("t1", None), ("t2", 1)]

    def first_defined(rs):
        vals = [v for _, v in rs if v is not None]
        return vals[0] if vals else None

    ci = stats.cluster_bootstrap(rows, lambda r: r[0], first_defined, seed=3, resamples=200)
    assert 0 < ci.undefined < 200


def test_small_cells_report_counts_only():
    assert stats.fmt_count(3, 11) == "3/11"
    assert stats.fmt_count(5, 20, (0.1, 0.45)) == "5/20 (25.0%, 10.0–45.0)"
    assert stats.fmt_count(0, 0) == "–"


def _reference_bootstrap(rows, cluster, statistic, seed, resamples=stats.BOOTSTRAP_RESAMPLES):
    """cluster_bootstrap as committed before the task-macro refactor."""
    import math
    import random
    from collections import defaultdict

    groups = defaultdict(list)
    for r in rows:
        groups[cluster(r)].append(r)
    keys = sorted(groups, key=str)
    rng = random.Random(seed)
    values, undefined = [], 0
    for _ in range(resamples):
        v = statistic([r for k in rng.choices(keys, k=len(keys)) for r in groups[k]])
        if v is None:
            undefined += 1
        else:
            values.append(v)
    est = statistic(list(rows))
    if not values:
        return stats.BootstrapCI(est, None, None, resamples, undefined)
    values.sort()
    lo = values[int(math.floor(0.025 * (len(values) - 1)))]
    hi = values[int(math.ceil(0.975 * (len(values) - 1)))]
    return stats.BootstrapCI(est, lo, hi, resamples, undefined)


def test_cluster_bootstrap_unchanged_by_task_macro_refactor():
    rows = [(f"t{i % 7}", (i * 37) % 5 == 0) for i in range(60)]

    def mean(rs):
        return sum(r[1] for r in rs) / len(rs) if rs else None

    def picky(rs):
        hits = [r for r in rs if r[0] in {"t1", "t2"}]
        return mean(hits) if hits else None

    for statistic in (mean, picky):
        for seed in (0, "s:1"):
            assert stats.cluster_bootstrap(
                rows, lambda r: r[0], statistic, seed=seed
            ) == _reference_bootstrap(rows, lambda r: r[0], statistic, seed)


def test_task_macro_weighs_each_task_once():
    rows = [("a", 1.0)] * 4 + [("b", 0.0)]
    assert stats.task_macro(rows, lambda r: r[0], lambda r: r[1]) == 0.5
    assert stats.task_macro([], lambda r: r[0], lambda r: r[1]) is None
    ci = stats.task_macro_bootstrap(rows, lambda r: r[0], lambda r: r[1], seed=3)
    assert ci.estimate == 0.5
    # Two clusters drawn with replacement: macro is 0, 0.5 or 1, never the micro 0.8
    assert ci.low == 0.0 and ci.high == 1.0 and ci.undefined == 0


def test_task_macro_bootstrap_counts_a_task_drawn_twice_twice():
    rows = [("a", 1.0)] * 9 + [("b", 0.0), ("c", 0.0), ("c", 1.0)]
    means = {"a": 1.0, "b": 0.0, "c": 0.5}

    sizes = {"a": 9, "b": 1, "c": 2}

    # Same draws as cluster_bootstrap, which concatenates whole tasks: walk the drawn rows a
    # task at a time and average the per-task means, one per drawn copy.
    def per_draw(rs):
        out, i = [], 0
        while i < len(rs):
            out.append(means[rs[i][0]])
            i += sizes[rs[i][0]]
        return sum(out) / len(out)

    expected = stats.cluster_bootstrap(rows, lambda r: r[0], per_draw, seed="macro")
    got = stats.task_macro_bootstrap(rows, lambda r: r[0], lambda r: r[1], seed="macro")
    assert got == expected
    assert got.estimate == pytest.approx(0.5)


def test_task_macro_bootstrap_single_task_is_degenerate():
    ci = stats.task_macro_bootstrap(
        [("a", 1.0), ("a", 0.0)], lambda r: r[0], lambda r: r[1], seed=1
    )
    assert (ci.estimate, ci.low, ci.high) == (0.5, 0.5, 0.5)
