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
