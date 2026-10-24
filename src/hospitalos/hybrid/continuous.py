"""Continuous, censor-aware distributions for the v2 research benchmark.

No estimator is imported here. Mixtures are of densities/survival functions,
never hazards. The Gaussian copula preserves each specified marginal.
"""

from __future__ import annotations

import math
from typing import Any, cast

import numpy as np
from scipy.special import ndtr, ndtri  # type: ignore[import-untyped]

Array = np.ndarray[Any, Any]
GRID = np.array([*range(30, 481, 30), 1440], dtype=float)
LEFT = np.r_[0.0, GRID[:-1]]
WIDTH = GRID - LEFT


def rates_from_hazards(hazards: Array) -> Array:
    if hazards.shape[-1] != len(GRID) or not np.all(np.isfinite(hazards)):
        raise ValueError("Invalid hazard grid")
    if np.any((hazards < 0) | (hazards >= 1)):
        raise ValueError("Hazards must be in [0,1)")
    return cast(Array, -np.log1p(-hazards) / WIDTH)


def survival(rates: Array, time: Array) -> Array:
    exposure = np.clip(np.asarray(time)[..., None] - LEFT, 0, WIDTH)
    return cast(Array, np.exp(-np.sum(rates * exposure, axis=-1)))


def density(rates: Array, time: Array) -> Array:
    index = np.minimum(np.searchsorted(GRID, time, side="left"), len(GRID) - 1)
    hazard = np.take_along_axis(rates, np.asarray(index)[..., None], axis=-1)[..., 0]
    return hazard * survival(rates, time)


def log_loss(
    rates: Array, time: Array, observed: Array, other: Array | None = None, alpha: float = 0
) -> Array:
    if not 0 <= alpha <= 1:
        raise ValueError("Invalid mixture weight")
    p = np.where(observed, density(rates, time), survival(rates, time))
    if other is not None:
        q = np.where(observed, density(other, time), survival(other, time))
        p = (1 - alpha) * p + alpha * q
    return cast(Array, -np.log(np.maximum(p, 1e-14)))


def quantiles(rates: Array, u: Array, other: Array | None = None, alpha: float = 0) -> Array:
    """Rows are patients, columns independent or copula-coupled scenario ranks."""
    if not 0 <= alpha <= 1 or np.any((u <= 0) | (u >= 1)):
        raise ValueError("Ranks must be inside (0,1), weight inside [0,1]")
    a = np.c_[np.ones(len(rates)), np.exp(-np.cumsum(rates * WIDTH, axis=1))]
    b = (
        a
        if other is None
        else np.c_[np.ones(len(other)), np.exp(-np.cumsum(other * WIDTH, axis=1))]
    )
    edge_survival = (1 - alpha) * a + alpha * b
    target = 1 - u
    index = np.sum(target[..., None] < edge_survival[:, None, 1:], axis=-1)
    tail = index == len(GRID)
    index = np.minimum(index, len(GRID) - 1)
    row = np.arange(len(rates))[:, None]
    sa, sb = a[row, index], b[row, index]
    ra = rates[row, index]
    rb = ra if other is None else other[row, index]
    lo, hi = np.zeros_like(u), WIDTH[index].copy()
    if other is None or alpha in (0, 1):
        s, r = (sb, rb) if alpha == 1 else (sa, ra)
        offset = -np.log(np.maximum(target / s, 1e-300)) / np.maximum(r, 1e-300)
    else:
        for _ in range(25):
            mid = (lo + hi) / 2
            value = (1 - alpha) * sa * np.exp(-ra * mid) + alpha * sb * np.exp(-rb * mid)
            lo = np.where(value > target, mid, lo)
            hi = np.where(value > target, hi, mid)
        offset = (lo + hi) / 2
    return np.where(tail, np.inf, LEFT[index] + offset)


def copula_uniforms(seed: int, patients: int, scenarios: int, loading: float) -> Array:
    if not 0 <= loading <= 1:
        raise ValueError("Invalid shared loading")
    # A dedicated shared and idiosyncratic stream makes the ranks policy independent.
    rng = np.random.default_rng(seed)
    common = rng.standard_normal((1, scenarios))
    noise = rng.standard_normal((patients, scenarios))
    u = ndtr(loading * common + math.sqrt(1 - loading**2) * noise)
    return cast(Array, np.clip(u, 1e-12, 1 - 1e-12))


def coupled_ranks(common: Array, individual: Array, loading: float) -> Array:
    if not 0 <= loading <= 1:
        raise ValueError("Invalid shared loading")
    return cast(
        Array,
        np.clip(
            ndtr(loading * ndtri(common) + math.sqrt(1 - loading**2) * ndtri(individual)),
            1e-12,
            1 - 1e-12,
        ),
    )


def isolated_gain(rates: Array, remaining: Array) -> Array:
    """Exact E[(remaining-T)+]; no Monte Carlo and no queue interaction claim."""
    length = np.clip(remaining[..., None] - LEFT, 0, WIDTH)
    left_survival = np.c_[np.ones(len(rates)), np.exp(-np.cumsum(rates * WIDTH, axis=1))][:, :-1]
    integral = left_survival * (-np.expm1(-rates * length)) / np.maximum(rates, 1e-300)
    integral = np.where(rates == 0, left_survival * length, integral)
    return cast(Array, np.maximum(remaining, 0) - np.sum(integral, axis=-1))
