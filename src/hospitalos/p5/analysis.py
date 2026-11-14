"""P5 analysis primitives (P5-PROTO-2 §§ 5.1, 6.3, 8). No result is computed at import.

* estimands: equal weight per structure, then per parent (records already averaged over
  twins/replicates by the caller);
* two-stage hierarchical bootstrap: structures with replacement, then parents with replacement
  inside each drawn structure; a parent record carries its twins, replicates and plans;
* capture ratio as a ratio of weighted sums, no clipping, undefined below the headroom threshold;
* twin precheck statistic theta (unsigned, replicate-variance corrected);
* structure-level one-sided Clopper-Pearson harm bound (valid under intra-structure dependence,
  non-degenerate at zero events).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

Structure = Sequence[dict[str, Any]]  # parent records of one structure


def binom_cdf(x: int, n: int, p: float) -> float:
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(x + 1))


def clopper_pearson_upper(x: int, n: int, alpha: float = 0.05) -> float:
    """One-sided (1-alpha) upper bound for a binomial proportion with x events among n."""
    if n <= 0:
        raise ValueError("n must be positive")
    if x >= n:
        return 1.0
    lo, hi = x / n, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if binom_cdf(x, n, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return hi


def structure_weighted_mean(structures: Sequence[Structure], key: str) -> float:
    means = [float(np.mean([p[key] for p in s])) for s in structures if len(s)]
    return float(np.mean(means))


def structure_weighted_sum_ratio(structures: Sequence[Structure], num: str, den: str) -> tuple[float, float]:
    """Ratio of structure-weighted means (= ratio of weighted sums) and the mean denominator."""
    n = structure_weighted_mean(structures, num)
    d = structure_weighted_mean(structures, den)
    return (n / d if d != 0 else math.nan), d


def capture(structures: Sequence[Structure], delta: float = 15.0) -> dict[str, Any]:
    """P5a-2: sum(U_hab - U_plan) / sum(U_hab - U_star); undefined if mean headroom < delta."""
    ratio, headroom = structure_weighted_sum_ratio(structures, "gain", "headroom")
    defined = headroom >= delta
    return {"capture": ratio if defined else None, "mean_headroom": headroom, "defined": defined, "clipped": False}


def hierarchical_bootstrap(
    structures: Sequence[Structure],
    stat: Callable[[list[list[dict[str, Any]]]], float],
    resamples: int,
    seed: int,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    out = np.empty(resamples)
    n_s = len(structures)
    for b in range(resamples):
        drawn = []
        for i in rng.integers(0, n_s, n_s):
            s = structures[int(i)]
            drawn.append([s[int(j)] for j in rng.integers(0, len(s), len(s))])
        out[b] = stat(drawn)
    return out


def percentile_interval(samples: np.ndarray, level: float = 0.95) -> tuple[float, float]:
    finite = samples[np.isfinite(samples)]
    a = (1 - level) / 2
    return float(np.quantile(finite, a)), float(np.quantile(finite, 1 - a))


def one_sided_lower(samples: np.ndarray, level: float = 0.95) -> float:
    return float(np.quantile(samples[np.isfinite(samples)], 1 - level))


def verdict(lower: float, upper: float, delta: float, guardrails_ok: bool, precision_ok: bool) -> str:
    if upper < delta:
        return "insufficient"
    if lower > delta and guardrails_ok and precision_ok:
        return "demonstrated_in_this_synthetic_protocol"
    return "inconclusive" if precision_ok else "exploratory"


def theta_term(g: Sequence[float]) -> float:
    """Unbiased estimate of d^2 from K replicate contrasts g_k: mean(g)^2 - var(g)/K."""
    k = len(g)
    if k < 2:
        raise ValueError("theta needs K >= 2 replicates")
    arr = np.asarray(g, dtype=float)
    return float(arr.mean() ** 2 - arr.var(ddof=1) / k)


def harm_bound(structure_harmed: Sequence[bool], alpha: float = 0.05) -> dict[str, Any]:
    n = len(structure_harmed)
    x = int(sum(bool(h) for h in structure_harmed))
    return {"n_structures": n, "harmed_structures": x, "upper_one_sided": clopper_pearson_upper(x, n, alpha)}
