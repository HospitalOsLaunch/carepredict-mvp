"""Pilot indicators: occupancy, closed beds, response speed, conversion, North Star.

North Star: bed-days recovered versus a pre-registered baseline, computed per
bed pool (site x mention) and summed:

    recovered = sum over pools p, period days d of (occupied_pd - baseline_rate_p * open_pd)

Only pools whose open-bed count is identical over the baseline and the period
are included. In a saturated unit, closing beds mechanically raises the
occupancy rate, so a rate-based comparison across a capacity change would
credit staffing closures to the product (found by running this metric on the
stationary demo data). Excluded pools are listed, never silently dropped.

Uncertainty comes from an empirical null ("placebo windows"): the same
before/after statistic is recomputed on pairs of windows of the same lengths
and gap, slid weekly across the history that precedes the baseline end, where
the product cannot have had any effect. The 80 % interval is

    estimate - mean(null) +/- 1.2816 * 1.25 * sd(null)

Calibration on the stationary synthetic generator (``seed.py``, which contains
no product effect), periods of 28, 84 and 116 days:

* a 7- or 28-day block bootstrap gave 25-30 % false positives instead of 10 %,
  because daily census is autocorrelated over about one length of stay;
* placebo windows match the true spread only when the history before the
  baseline end covers at least 3 times the span (baseline + gap + period);
  with 1.5 times, the spread was underestimated by about 35 %. Below 3 times,
  no interval is given and no success fee can be triggered;
* with enough history (60 replicates), the standardised statistic has a
  standard deviation of 1.09-1.23 instead of 1 and a mean of -0.2: hence the
  1.25 widening factor. The residual bias makes negative results slightly
  over-detected; a negative estimate is not, on its own, proof of harm.

The success fee is due only when the lower bound of the widened 80 % interval
is above zero: about 2-7 % false positives on the synthetic generator. These
numbers must be re-measured on each group's real history before contracting.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import median

from services.admissions_smr.domain.forecast import StayRecord


@dataclass(frozen=True)
class CapacityPoint:
    site_id: int
    mention: str
    effective_date: date
    beds_installed: int
    beds_open: int
    reason: str


@dataclass(frozen=True)
class PoolCapacity:
    site_id: int
    mention: str
    beds_installed: int
    beds_open: int


def date_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=k) for k in range((end - start).days + 1)]


def daily_occupancy(stays: Iterable[StayRecord], start: date, end: date) -> dict[date, int]:
    """End-of-day census for each day of [start, end]."""
    days = date_range(start, end)
    occ = dict.fromkeys(days, 0)
    for s in stays:
        first = max(start, s.admission_date)
        last_present = (
            end if s.discharge_date is None else min(end, s.discharge_date - timedelta(days=1))
        )
        d = first
        while d <= last_present:
            occ[d] += 1
            d += timedelta(days=1)
    return occ


def pool_capacity(
    changes: Sequence[CapacityPoint],
    current: Sequence[PoolCapacity],
    start: date,
    end: date,
) -> dict[tuple[int, str], dict[date, tuple[int, int, str]]]:
    """(installed, open, reason of the latest change) per pool and per day.

    The capacity on day ``d`` is the latest change effective on or before
    ``d``; before the first recorded change, the earliest known capacity
    applies (current values when no change was ever recorded).
    """
    by_pool: dict[tuple[int, str], list[CapacityPoint]] = {}
    for c in sorted(changes, key=lambda c: c.effective_date):
        by_pool.setdefault((c.site_id, c.mention), []).append(c)
    days = date_range(start, end)
    out: dict[tuple[int, str], dict[date, tuple[int, int, str]]] = {}
    for pool in current:
        key = (pool.site_id, pool.mention)
        history = by_pool.get(key, [])
        series: dict[date, tuple[int, int, str]] = {}
        idx = -1
        for d in days:
            while idx + 1 < len(history) and history[idx + 1].effective_date <= d:
                idx += 1
            if idx >= 0:
                point = history[idx]
                series[d] = (point.beds_installed, point.beds_open, point.reason)
            elif history:
                point = history[0]
                series[d] = (point.beds_installed, point.beds_open, point.reason)
            else:
                series[d] = (pool.beds_installed, pool.beds_open, "autre")
        out[key] = series
    return out


def daily_capacity(
    changes: Sequence[CapacityPoint],
    current: Sequence[PoolCapacity],
    start: date,
    end: date,
) -> dict[date, tuple[int, int, dict[str, int]]]:
    """(installed, open, closed beds by reason) per day, summed over pools."""
    per_pool = pool_capacity(changes, current, start, end)
    result: dict[date, tuple[int, int, dict[str, int]]] = {}
    for d in date_range(start, end):
        installed = 0
        opened = 0
        closed_by_reason: Counter[str] = Counter()
        for series in per_pool.values():
            inst, op, reason = series[d]
            installed += inst
            opened += op
            if inst > op:
                closed_by_reason[reason] += inst - op
        result[d] = (installed, opened, dict(closed_by_reason))
    return result


@dataclass(frozen=True)
class OccupancySummary:
    days: int
    occupied_bed_days: int
    open_bed_days: int
    installed_bed_days: int
    rate_on_open: float | None
    rate_on_installed: float | None
    avg_closed_beds: float
    closed_bed_days_by_reason: dict[str, int]


def summarise_occupancy(
    occ: Mapping[date, int], cap: Mapping[date, tuple[int, int, dict[str, int]]]
) -> OccupancySummary:
    days = sorted(occ)
    occupied = sum(occ[d] for d in days)
    opened = sum(cap[d][1] for d in days)
    installed = sum(cap[d][0] for d in days)
    closed_reasons: Counter[str] = Counter()
    for d in days:
        closed_reasons.update(cap[d][2])
    return OccupancySummary(
        days=len(days),
        occupied_bed_days=occupied,
        open_bed_days=opened,
        installed_bed_days=installed,
        rate_on_open=round(occupied / opened, 4) if opened else None,
        rate_on_installed=round(occupied / installed, 4) if installed else None,
        avg_closed_beds=round((installed - opened) / len(days), 2) if days else 0.0,
        closed_bed_days_by_reason=dict(closed_reasons),
    )


@dataclass(frozen=True)
class RequestRecord:
    request_id: int
    received_at: datetime
    status: str
    first_response_at: datetime | None
    refusal_reason: str | None
    loss_reason: str | None
    was_accorded: bool


@dataclass(frozen=True)
class RequestSummary:
    received: int
    responded: int
    response_hours_median: float | None
    response_hours_p90: float | None
    responded_within_24h: float | None
    by_status: dict[str, int]
    accord_rate: float | None
    conversion_rate: float | None
    lost_after_accord_rate: float | None
    refusal_reasons: dict[str, int]
    loss_reasons: dict[str, int]


def summarise_requests(requests: Sequence[RequestRecord]) -> RequestSummary:
    hours = sorted(
        (r.first_response_at - r.received_at).total_seconds() / 3600.0
        for r in requests
        if r.first_response_at is not None
    )
    by_status = Counter(r.status for r in requests)
    accorded = [r for r in requests if r.was_accorded]
    lost_after = [r for r in accorded if r.status == "perdue"]
    n = len(requests)
    return RequestSummary(
        received=n,
        responded=len(hours),
        response_hours_median=round(median(hours), 1) if hours else None,
        response_hours_p90=round(_percentile(hours, 0.9), 1) if hours else None,
        responded_within_24h=round(sum(1 for h in hours if h <= 24) / len(hours), 3)
        if hours
        else None,
        by_status=dict(by_status),
        accord_rate=round(len(accorded) / n, 3) if n else None,
        conversion_rate=round(by_status.get("admise", 0) / n, 3) if n else None,
        lost_after_accord_rate=round(len(lost_after) / len(accorded), 3) if accorded else None,
        refusal_reasons=dict(Counter(r.refusal_reason for r in requests if r.refusal_reason)),
        loss_reasons=dict(Counter(r.loss_reason for r in requests if r.loss_reason)),
    )


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        raise ValueError("empty")
    idx = q * (len(sorted_values) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (idx - lo)


@dataclass(frozen=True)
class PoolSeries:
    """Daily census and open beds of one pool, over the whole available history."""

    key: str
    occupied: Mapping[date, int]
    open_beds: Mapping[date, int]


@dataclass(frozen=True)
class NorthStar:
    baseline_rate: float
    period_rate: float
    recovered_bed_days: float
    recovered_low: float | None
    recovered_high: float | None
    value_eur: float
    value_low_eur: float | None
    value_high_eur: float | None
    success_fee_eur: float
    period_days: int
    baseline_days: int
    placebo_windows: int
    included_pools: list[str]
    excluded_pools: dict[str, str]
    interval_note: str


MIN_HISTORY_SPANS = 3.0
PLACEBO_STEP_DAYS = 7
Z_80 = 1.2816
INTERVAL_WIDENING = 1.25


def _constant_open(series: PoolSeries, days: Sequence[date]) -> int | None:
    values = {series.open_beds.get(d) for d in days}
    if len(values) != 1:
        return None
    value = values.pop()
    return value if value else None


def _statistic(
    pools: Sequence[tuple[PoolSeries, int]], b_days: Sequence[date], p_days: Sequence[date]
) -> tuple[float, float, float]:
    total = occ_b = occ_p = open_b = open_p = 0.0
    for series, beds in pools:
        ob = sum(series.occupied.get(d, 0) for d in b_days)
        op = sum(series.occupied.get(d, 0) for d in p_days)
        rate_b = ob / (beds * len(b_days))
        total += op - rate_b * beds * len(p_days)
        occ_b += ob
        occ_p += op
        open_b += beds * len(b_days)
        open_p += beds * len(p_days)
    return occ_b / open_b, occ_p / open_p, total


def north_star(
    pools: Sequence[PoolSeries],
    baseline: tuple[date, date],
    period: tuple[date, date],
    value_per_bed_day: float,
    success_fee_rate: float,
    history_start: date,
) -> NorthStar | None:
    b_days = date_range(*baseline)
    p_days = date_range(*period)
    if not b_days or not p_days or period[0] <= baseline[1]:
        return None

    excluded: dict[str, str] = {}
    included: list[tuple[PoolSeries, int]] = []
    for series in pools:
        beds = _constant_open(series, list(b_days) + list(p_days))
        if beds is None:
            excluded[series.key] = "capacité ouverte modifiée entre la référence et la période"
        else:
            included.append((series, beds))
    if not included:
        return None

    rate_b, rate_p, point = _statistic(included, b_days, p_days)

    # Placebo pairs: same lengths and gap, ending no later than the baseline end.
    gap = (period[0] - baseline[1]).days - 1
    span = len(b_days) + gap + len(p_days)
    nulls: list[float] = []
    end = baseline[1]
    while (end - history_start).days + 1 >= span:
        pb_start = end - timedelta(days=span - 1)
        pb_days = date_range(pb_start, pb_start + timedelta(days=len(b_days) - 1))
        pp_days = date_range(end - timedelta(days=len(p_days) - 1), end)
        window = list(pb_days) + list(pp_days)
        if all(_constant_open(series, window) == beds for series, beds in included):
            nulls.append(_statistic(included, pb_days, pp_days)[2])
        end -= timedelta(days=PLACEBO_STEP_DAYS)

    low: float | None = None
    high: float | None = None
    history_days = (baseline[1] - history_start).days + 1
    spans = history_days / span
    if spans >= MIN_HISTORY_SPANS and len(nulls) >= 2:
        mean_null = sum(nulls) / len(nulls)
        sd_null = (sum((x - mean_null) ** 2 for x in nulls) / len(nulls)) ** 0.5
        half_width = Z_80 * INTERVAL_WIDENING * sd_null
        low = point - mean_null - half_width
        high = point - mean_null + half_width
        note = (
            f"Intervalle à 80 % estimé sur {len(nulls)} fenêtres placebo couvrant "
            f"{history_days} jours d'historique avant la fin de la référence."
        )
    else:
        need = int(MIN_HISTORY_SPANS * span)
        note = (
            f"Historique insuffisant pour estimer l'incertitude : {history_days} jours avant la "
            f"fin de la référence, {need} requis (3 fois référence + écart + période). "
            "Aucun intéressement ne peut être déclenché."
        )

    value = point * value_per_bed_day
    fee = round(value * success_fee_rate, 0) if low is not None and low > 0 else 0.0
    return NorthStar(
        baseline_rate=round(rate_b, 4),
        period_rate=round(rate_p, 4),
        recovered_bed_days=round(point, 1),
        recovered_low=None if low is None else round(low, 1),
        recovered_high=None if high is None else round(high, 1),
        value_eur=round(value, 0),
        value_low_eur=None if low is None else round(low * value_per_bed_day, 0),
        value_high_eur=None if high is None else round(high * value_per_bed_day, 0),
        # Pre-registered rule: no fee unless the whole 80 % interval is above zero.
        success_fee_eur=fee,
        period_days=len(p_days),
        baseline_days=len(b_days),
        placebo_windows=len(nulls),
        included_pools=[series.key for series, _ in included],
        excluded_pools=excluded,
        interval_note=note,
    )
