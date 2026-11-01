"""Conformal prediction intervals: split conformal per horizon, and its online adaptation.

Split conformal (signed residuals, two-sided): with calibration residuals
r = y − ŷ of past forecasts at the same horizon, the interval for a new forecast is
[ŷ + r_(lo), ŷ + r_(hi)] with the finite-sample ranks lo = ⌊(n+1)·α/2⌋ and
hi = ⌈(n+1)·(1 − α/2)⌉. Signed residuals keep the asymmetry of count data.
Reference: Lei, G'Sell, Rinaldo, Tibshirani & Wasserman, "Distribution-Free Predictive
Inference for Regression", JASA 2018.

Adaptive conformal inference (ACI): the level is updated online from the realised
misses, α_{t+1} = α_t + γ (α − err_t), so intervals widen when they start missing (a
regime shift such as an epidemic wave) and narrow back afterwards. Its long-run miss
rate stays within (max(α₁, 1 − α₁) + γ) / (γ T) of α for any sequence.
Reference: Gibbs & Candès, "Adaptive Conformal Inference Under Distribution Shift",
NeurIPS 2021, https://arxiv.org/abs/2106.00170 (equation 2).

Two practical choices, stated: the calibration set is a rolling window of the latest
residuals (so the residual scale also follows the shift), and when α_t ≤ 0 the interval
is the full range of that window instead of the whole real line (an infinite interval
is useless for beds); when α_t ≥ 1 it shrinks to the median residual. A forecast at
horizon ``lag`` only learns its outcome ``lag`` steps later: the update waits for it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

ALPHA = 0.2  # 80 % intervals (q10, q90)
GAMMA = 0.2  # ACI step size (amendment A2 of docs/liscop/BACKTEST.md)
WINDOW = 56  # calibration residuals kept (8 weeks of daily forecasts)
MIN_CALIBRATION = 10

Residuals = Sequence[float] | npt.NDArray[np.float64]


def conformal_offsets(residuals: Residuals, alpha: float) -> tuple[float, float]:
    """Lower and upper residual offsets of the (1 − alpha) split conformal interval."""
    r = np.sort(np.asarray(residuals, dtype=float))
    n = len(r)
    if n == 0:
        raise ValueError("conformal intervals need at least one residual")
    if alpha <= 0:
        return float(r[0]), float(r[-1])
    if alpha >= 1:
        mid = float(np.median(r))
        return mid, mid
    lo_rank = max(1, math.floor((n + 1) * alpha / 2))
    hi_rank = min(n, math.ceil((n + 1) * (1 - alpha / 2)))
    return float(r[lo_rank - 1]), float(r[hi_rank - 1])


@dataclass(frozen=True)
class AciTrace:
    """One pass of ACI over a residual sequence, in time order."""

    alpha_used: list[float]  # level used for the interval of each step
    covered: list[bool | None]  # None when the calibration window was too short
    next_alpha: float  # level for the next forecast, once every outcome is known
    next_offsets: tuple[float, float]  # residual offsets for the next forecast


def adaptive_conformal(
    residuals: Residuals,
    alpha: float = ALPHA,
    gamma: float = GAMMA,
    window: int = WINDOW,
    lag: int = 1,
    min_calibration: int = MIN_CALIBRATION,
) -> AciTrace:
    """Replay ACI over ``residuals`` (one per step, oldest first) at a horizon of ``lag``.

    At step i the interval only uses residuals and misses known at forecast time: those of
    steps ≤ i − lag. Steps whose calibration window holds fewer than ``min_calibration``
    residuals get no interval and do not update the level.
    """
    if lag < 1:
        raise ValueError("lag must be at least 1")
    r = np.asarray(residuals, dtype=float)
    alpha_used: list[float] = []
    covered: list[bool | None] = []
    feedback = 0.0  # γ · Σ (α − err_j) over the revealed steps j
    for i in range(len(r)):
        revealed = i - lag  # last step whose outcome is known
        if revealed >= 0 and covered[revealed] is not None:
            feedback += gamma * (alpha - (0.0 if covered[revealed] else 1.0))
        level = alpha + feedback
        alpha_used.append(level)
        calibration = r[max(0, revealed + 1 - window) : revealed + 1]
        if len(calibration) < min_calibration:
            covered.append(None)
            continue
        lo, hi = conformal_offsets(calibration, level)
        covered.append(bool(lo <= r[i] <= hi))
    # Next forecast: every outcome above is known by then.
    for j in range(max(0, len(r) - lag), len(r)):
        if covered[j] is not None:
            feedback += gamma * (alpha - (0.0 if covered[j] else 1.0))
    next_alpha = alpha + feedback
    tail = r[-window:]
    next_offsets = conformal_offsets(tail, next_alpha) if len(tail) else (0.0, 0.0)
    return AciTrace(alpha_used, covered, next_alpha, next_offsets)
