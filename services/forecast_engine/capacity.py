"""Available beds and tension by Monte Carlo, per unit and day, then summed by scope.

For one unit, with D the discharges and A the arrivals, day k = 0..H-1 (J+0..J+7):

    occupied_k  = occupied at 00:00 on J+0 + Σ_{j≤k} A_j − Σ_{j≤k} D_j
    available_k = open_k − occupied_k          (stored clipped to [0, open_k])

- Discharges of the patients present: one uniform draw per patient through the
  patient's own cumulative probabilities (the existing discharge model, see
  ``services/admissions_smr/domain/forecast.py``), so a patient leaves at most once and
  the days are consistent with each other.
- Arrivals: a count distribution matched to the arrivals forecast (centre = conformal
  median, spread = the 80 % conformal interval). It is a gamma-Poisson mixture, i.e. a
  negative binomial: λ = μ · G_common · G_unit, A ~ Poisson(λ), with G ~ Gamma(1/v, v)
  (mean 1, variance v). The unit variance v_u is set so that Var(A) = μ + μ²/r, r being the
  negative binomial size whose 10-90 % width matches the conformal interval (Poisson when
  the interval is not wider than Poisson). Chosen because counts are over-dispersed
  (weekly and epidemic effects), the interval is already calibrated (and widened by
  ACI under drift), and it needs nothing beyond numpy.
- Promised admissions (accepted requests, emergency patients already waiting for this
  unit) are a floor on cumulative arrivals: A_cum = max(promised_cum, sampled A_cum), i.e.
  available = open − occupied − promised + discharges − arrivals not already promised.
- Weekday practice (fewer discharges at weekends, more on Monday) is not in the discharge
  model; a share of each day's discharges is postponed to the next day so that the
  observed weekday profile is reproduced (``weekday_retention``).
- Patients arriving within the horizon may also leave within it: each day's arrivals
  leave on the following days by a multinomial draw from the length-of-stay law of a new
  stay of the unit (same discharge model, time spent = 0).

Aggregation (site, group, GHT, département): draws are summed unit by unit, draw by draw.
Discharges are independent between patients. Arrivals share one common daily factor
G_common (same draw for every unit of the run), whose variance is estimated from the
covariance of the units' relative forecast errors: epidemics and weekdays hit every unit
together, and assuming independence would make the group's interval too narrow.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from services.admissions_smr.domain.ror import TENSION_NORMAL_MIN

DRAWS = 2_000
SEED = 2026
Z80 = 1.2815515655446004  # standard normal 90 % quantile: q90 − q10 = 2 · Z80 · sd
MAX_COMMON_VARIANCE = 0.1

IntDraws = npt.NDArray[np.int64]
FloatArray = npt.NDArray[np.float64]


def nb_size(mean: float, q10: float, q90: float) -> float:
    """Negative binomial size r with Var = mean + mean²/r matching the 10-90 % width."""
    sd = max(0.0, q90 - q10) / (2 * Z80)
    excess = sd * sd - mean
    if mean <= 0 or excess <= 0:
        return float("inf")
    return mean * mean / excess


def gamma_factor(variance: float, shape: tuple[int, ...], rng: np.random.Generator) -> FloatArray:
    """Mean-one gamma multipliers of the given variance (ones when the variance is 0)."""
    if variance <= 1e-12:
        return np.ones(shape)
    return rng.gamma(1.0 / variance, variance, size=shape)


def sample_counts(
    centre: Sequence[float] | FloatArray,
    q10: Sequence[float] | FloatArray,
    q90: Sequence[float] | FloatArray,
    rng: np.random.Generator,
    common: FloatArray | None = None,
    common_variance: float = 0.0,
    draws: int = DRAWS,
) -> IntDraws:
    """Integer draws (draws × days) of a count forecast; ``common`` is a shared factor."""
    days = len(centre)
    lam = np.empty((draws, days))
    for k in range(days):
        mu = max(0.0, float(centre[k]))
        r = nb_size(mu, float(q10[k]), float(q90[k]))
        unit_var = max(0.0, (1 + 1 / r) / (1 + common_variance) - 1)
        lam[:, k] = mu * gamma_factor(unit_var, (draws,), rng)
    if common is not None:
        lam *= common
    return rng.poisson(lam).astype(np.int64)


def weekday_retention(factors: Sequence[float], rounds: int = 4) -> list[float]:
    """Share of the discharges due on each weekday that happen that day (Monday first).

    ``factors`` is the observed discharge profile (mean discharges on each weekday over the
    overall daily mean). The discharge model has no calendar: it spreads discharges evenly
    over the week. Postponing, on each day, the part above what that day usually sees to
    the next day reproduces the profile (weekend discharges done on Monday) while keeping
    the weekly total. Solved by going round the week until the carried part settles.
    """
    f = [max(0.0, x) for x in factors]
    carry = 0.0  # carried in, in units of one average day
    keep = [1.0] * 7
    for _ in range(rounds):
        for d in range(7):
            due = 1.0 + carry
            keep[d] = min(1.0, f[d] / due)
            carry = due * (1.0 - keep[d])
    return keep


def common_shock_variance(relative_errors: Iterable[FloatArray]) -> float:
    """Mean covariance between the relative errors of different series (aligned by date).

    Under λ_u = μ_u · G_common · G_u, Cov(A_u/μ_u, A_v/μ_v) = Var(G_common) for u ≠ v.
    """
    rows = [np.asarray(e, dtype=float) for e in relative_errors if len(e) > 2]
    if len(rows) < 2:
        return 0.0
    n = min(len(r) for r in rows)
    cov = np.cov(np.vstack([r[-n:] for r in rows]))
    off = cov[~np.eye(len(rows), dtype=bool)]
    return float(np.clip(off.mean(), 0.0, MAX_COMMON_VARIANCE))


@dataclass(frozen=True)
class UnitInputs:
    key: int
    installed: Sequence[int]  # per day
    open_beds: Sequence[int]  # per day
    occupied: int  # at 00:00 on the first day
    discharge_cdfs: FloatArray  # patients × days: P(discharged by the end of day k)
    new_stay_cdf: FloatArray  # days: P(a stay admitted on day j left by day j + k)
    promised_cum: Sequence[int]  # promised arrivals due by the end of day k
    arrivals_centre: Sequence[float] | FloatArray
    arrivals_q10: Sequence[float] | FloatArray
    arrivals_q90: Sequence[float] | FloatArray
    discharge_retention: Sequence[float] = ()  # per day; empty = no weekday postponement


@dataclass(frozen=True)
class UnitDraws:
    available: IntDraws  # draws × days, clipped to [0, open beds]
    available_raw: IntDraws  # unclipped (negative = patients without a bed)
    arrivals: IntDraws  # daily
    discharges: IntDraws  # daily


def simulate_unit(
    unit: UnitInputs,
    rng: np.random.Generator,
    common: FloatArray | None = None,
    common_variance: float = 0.0,
    draws: int = DRAWS,
) -> UnitDraws:
    days = len(unit.open_beds)
    # Discharges of the patients present: day index of each patient's discharge (days = later).
    cdfs = np.asarray(unit.discharge_cdfs, dtype=float).reshape(-1, days)
    u = rng.random((draws, cdfs.shape[0]))
    leave_day = (u[:, :, None] > cdfs[None, :, :]).sum(axis=2)
    discharges = np.stack([(leave_day == k).sum(axis=1) for k in range(days)], axis=1)

    sampled = sample_counts(
        unit.arrivals_centre,
        unit.arrivals_q10,
        unit.arrivals_q90,
        rng,
        common,
        common_variance,
        draws,
    )
    floor = np.asarray(unit.promised_cum, dtype=np.int64)
    arrivals_cum = np.maximum(np.cumsum(sampled, axis=1), floor[None, :])
    arrivals = np.diff(arrivals_cum, axis=1, prepend=0)

    # Arrivals of day j leave on day j + d by a multinomial draw on the new-stay law.
    new_cdf = np.clip(np.maximum.accumulate(np.asarray(unit.new_stay_cdf, dtype=float)), 0, 1)
    pmf = np.diff(new_cdf, prepend=0.0)
    for j in range(days):
        span = days - j
        pvals = np.append(pmf[:span], max(0.0, 1.0 - pmf[:span].sum()))
        moved = rng.multinomial(arrivals[:, j], pvals / pvals.sum())
        discharges[:, j:] += moved[:, :span]

    # Weekday practice: a discharge not kept on its day moves to the next day.
    carry = np.zeros(draws, dtype=np.int64)
    for k, keep in enumerate(unit.discharge_retention):
        due = discharges[:, k] + carry
        discharges[:, k] = rng.binomial(due, min(1.0, max(0.0, keep)))
        carry = due - discharges[:, k]

    occupied = unit.occupied + arrivals_cum - np.cumsum(discharges, axis=1)
    open_beds = np.asarray(unit.open_beds, dtype=np.int64)
    raw = open_beds[None, :] - occupied
    return UnitDraws(
        available=np.clip(raw, 0, open_beds[None, :]),
        available_raw=raw.astype(np.int64),
        arrivals=arrivals.astype(np.int64),
        discharges=discharges.astype(np.int64),
    )


@dataclass(frozen=True)
class Summary:
    mean: FloatArray
    q10: FloatArray
    q50: FloatArray
    q90: FloatArray


def summarise(draws: IntDraws | FloatArray) -> Summary:
    q10, q50, q90 = np.quantile(draws, [0.1, 0.5, 0.9], axis=0, method="inverted_cdf")
    return Summary(draws.mean(axis=0), q10, q50, q90)


def tension_probabilities(
    available: IntDraws, installed: Sequence[int] | IntDraws
) -> tuple[FloatArray, FloatArray]:
    """P(tension or critique) and P(critique) per day, with the LISCOP thresholds.

    Critique: no available bed. Tension: available below TENSION_NORMAL_MIN of the
    installed beds (``services/admissions_smr/domain/ror.py``). ``available`` is clipped.
    """
    beds = np.asarray(installed, dtype=float)[None, :]
    critique = available <= 0
    tension = critique | (available < TENSION_NORMAL_MIN * beds)
    return tension.mean(axis=0), critique.mean(axis=0)


def aggregate(
    draws_by_key: Mapping[int, IntDraws], scope_of: Mapping[int, str]
) -> dict[str, IntDraws]:
    """Sum the draws of every key, draw by draw, within each scope key."""
    out: dict[str, IntDraws] = {}
    for key, draws in draws_by_key.items():
        scope = scope_of.get(key)
        if scope is None:
            continue
        out[scope] = out[scope] + draws if scope in out else draws.copy()
    return out
