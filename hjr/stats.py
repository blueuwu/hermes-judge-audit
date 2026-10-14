"""Interval estimates and paired tests used by the Phase 2 analysis (prereg "Analysis rules").

* Wilson intervals for independent proportions.
* Task-clustered percentile bootstrap for anything aggregated over boundaries: tasks are
  resampled with replacement, and every boundary of a drawn task comes along. The same draws
  give task-macro intervals (the mean of per-task means).
* Exact McNemar (two-sided binomial on the discordant pairs) and Holm's step-down correction.
* Exact one-sided sign-flip test on per-task differences.
* Cohen's kappa, always reported next to prevalence and PABAK.
"""

from __future__ import annotations

import itertools
import math
import random
from collections import defaultdict
from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction

from scipy.stats import binomtest

Z95 = 1.959963984540054
BOOTSTRAP_RESAMPLES = 2000
# Fewer discordant pairs than this: "no detectable difference at n = ..."
MIN_DISCORDANT = 15
# Cells with fewer items report counts, not percentages.
MIN_ITEMS_FOR_PERCENT = 20


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def clopper_pearson(k: int, n: int) -> tuple[float, float] | None:
    """Exact two-sided 95% binomial interval."""
    if n == 0:
        return None
    ci = binomtest(k, n).proportion_ci(confidence_level=0.95, method="exact")
    return float(ci.low), float(ci.high)


@dataclass(frozen=True)
class BootstrapCI:
    estimate: float | None
    low: float | None
    high: float | None
    resamples: int
    # Resamples in which the statistic was undefined (e.g. no item of the needed class)
    undefined: int


def cluster_bootstrap[T](
    rows: Sequence[T],
    cluster: Callable[[T], Hashable],
    statistic: Callable[[Sequence[T]], float | None],
    *,
    seed: int | str,
    resamples: int = BOOTSTRAP_RESAMPLES,
    level: float = 0.95,
) -> BootstrapCI:
    """Percentile interval from resampling whole clusters (tasks) with replacement."""
    groups = _groups(rows, cluster)
    return _percentile(
        statistic(list(rows)),
        (
            statistic([r for k in drawn for r in groups[k]])
            for drawn in _draws(groups, seed, resamples)
        ),
        resamples,
        level,
    )


def task_macro[T](rows: Sequence[T], cluster: Callable[[T], Hashable], value) -> float | None:
    """Mean over clusters of each cluster's mean ``value``: every task weighs the same."""
    groups = _groups(rows, cluster)
    return _macro([[value(r) for r in groups[k]] for k in groups])


def task_macro_bootstrap[T](
    rows: Sequence[T],
    cluster: Callable[[T], Hashable],
    value: Callable[[T], float],
    *,
    seed: int | str,
    resamples: int = BOOTSTRAP_RESAMPLES,
    level: float = 0.95,
) -> BootstrapCI:
    """Task-macro mean with a percentile interval from resampling whole tasks. A task drawn
    twice counts twice, so each draw, not each distinct task, carries equal weight."""
    groups = _groups(rows, cluster)
    means = {k: [value(r) for r in g] for k, g in groups.items()}
    return _percentile(
        _macro(list(means.values())),
        (_macro([means[k] for k in drawn]) for drawn in _draws(groups, seed, resamples)),
        resamples,
        level,
    )


def _groups[T](rows: Sequence[T], cluster: Callable[[T], Hashable]) -> dict[Hashable, list[T]]:
    groups: dict[Hashable, list[T]] = defaultdict(list)
    for r in rows:
        groups[cluster(r)].append(r)
    return groups


def _draws(groups: Mapping[Hashable, list], seed: int | str, resamples: int):
    keys = sorted(groups, key=str)
    rng = random.Random(seed)
    for _ in range(resamples):
        yield rng.choices(keys, k=len(keys))


def _macro(groups: Sequence[Sequence[float]]) -> float | None:
    means = [sum(g) / len(g) for g in groups if g]
    return sum(means) / len(means) if means else None


def _percentile(
    est: float | None, draws: Iterable[float | None], resamples: int, level: float
) -> BootstrapCI:
    values: list[float] = []
    undefined = 0
    for v in draws:
        if v is None:
            undefined += 1
        else:
            values.append(v)
    if not values:
        return BootstrapCI(est, None, None, resamples, undefined)
    values.sort()
    alpha = (1 - level) / 2
    lo = values[int(math.floor(alpha * (len(values) - 1)))]
    hi = values[int(math.ceil((1 - alpha) * (len(values) - 1)))]
    return BootstrapCI(est, lo, hi, resamples, undefined)


@dataclass(frozen=True)
class McNemar:
    # b: only the first condition has the property; c: only the second
    b: int
    c: int
    p: float | None

    @property
    def discordant(self) -> int:
        return self.b + self.c

    @property
    def detectable(self) -> bool:
        return self.discordant >= MIN_DISCORDANT


def mcnemar_exact(first: Sequence[bool], second: Sequence[bool]) -> McNemar:
    if len(first) != len(second):
        raise ValueError("McNemar needs paired observations")
    b = sum(x and not y for x, y in zip(first, second, strict=True))
    c = sum(y and not x for x, y in zip(first, second, strict=True))
    p = binomtest(b, b + c, 0.5).pvalue if b + c else None
    return McNemar(b, c, p)


@dataclass(frozen=True)
class SignFlip:
    positive: int  # clusters with a positive difference
    nonzero: int  # clusters with a nonzero difference; zeros carry no sign
    p: float | None


def sign_flip_exact(values: Sequence[Fraction]) -> SignFlip:
    """One-sided exact sign-flip test of mean > 0: the share of the 2^m sign assignments to the
    m nonzero values whose sum is at least the observed sum. Exact arithmetic, no sampling."""
    nonzero = [abs(v) for v in values if v != 0]
    if len(nonzero) > 20:
        raise ValueError("exact sign-flip enumeration is limited to 20 nonzero clusters")
    positive = sum(v > 0 for v in values)
    if not nonzero:
        return SignFlip(0, 0, None)
    observed = sum(values, Fraction(0))
    hits = sum(
        sum((v if keep else -v for v, keep in zip(nonzero, signs, strict=True)), Fraction(0))
        >= observed
        for signs in itertools.product((True, False), repeat=len(nonzero))
    )
    return SignFlip(positive, len(nonzero), hits / 2 ** len(nonzero))


def holm(pvalues: Mapping[str, float | None]) -> dict[str, float | None]:
    """Holm step-down adjusted p-values. Tests without a p-value stay None and are not counted."""
    tested = sorted(((p, k) for k, p in pvalues.items() if p is not None), key=lambda t: t[0])
    m = len(tested)
    out: dict[str, float | None] = {k: None for k in pvalues}
    running = 0.0
    for i, (p, k) in enumerate(tested):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = running
    return out


@dataclass(frozen=True)
class Agreement:
    n: int
    observed: float | None
    kappa: float | None
    pabak: float | None
    # Share of each category over both raters' labels
    prevalence: dict[str, float]


def agreement(pairs: Sequence[tuple[str, str]], categories: Sequence[str]) -> Agreement:
    """Cohen's kappa for two raters, with prevalence and PABAK (k categories)."""
    n = len(pairs)
    if n == 0:
        return Agreement(0, None, None, None, {})
    po = sum(a == b for a, b in pairs) / n
    first = {c: sum(a == c for a, _ in pairs) / n for c in categories}
    second = {c: sum(b == c for _, b in pairs) / n for c in categories}
    pe = sum(first[c] * second[c] for c in categories)
    kappa = None if pe == 1 else (po - pe) / (1 - pe)
    k = len(categories)
    pabak = (k * po - 1) / (k - 1)
    prevalence = {c: (first[c] + second[c]) / 2 for c in categories}
    return Agreement(n, po, kappa, pabak, prevalence)


def fmt_count(k: int, n: int, ci: tuple[float, float] | None = None) -> str:
    """'k/n' below MIN_ITEMS_FOR_PERCENT items; otherwise with a percentage and interval."""
    if n == 0:
        return "–"
    if n < MIN_ITEMS_FOR_PERCENT:
        return f"{k}/{n}"
    out = f"{k}/{n} ({100 * k / n:.1f}%"
    if ci is not None:
        out += f", {100 * ci[0]:.1f}–{100 * ci[1]:.1f}"
    return out + ")"
