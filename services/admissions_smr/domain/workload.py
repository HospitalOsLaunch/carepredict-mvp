"""Care workload forecast (charge en soins) per bed pool, J+0 to J+H, against planned staff.

For each day ``k`` of the horizon, the expected care time is the sum of:

* patients already present: probability of still being there that day times
  the daily minutes of their care level (a patient leaving on day ``k`` is
  still cared for that day, plus the discharge workload);
* admissions already promised for that day or before (accords, confirmations);
* admissions not yet known: the pool's recent admission rate for that weekday,
  minus what is already promised that day, capped by the free beds expected.

Minutes per care level and per admission / discharge are group settings. The
defaults are stated hypotheses to calibrate against the units' own workload
tool (SIIPS, PMSI dependency scores...), never measured facts.

Uncertainty: presences and discharges are independent Bernoullis, unknown
admissions a Poisson count; the 80 % interval uses a normal approximation of
the total, which is reasonable for units of 15+ beds.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from services.admissions_smr.domain.forecast import (
    DEFAULT_PLAN_SLIP,
    HazardModel,
    StayRecord,
    discharge_cdf,
)

Z_80 = 1.2816

DEFAULT_CARE_MINUTES: Mapping[str, float] = {
    "1": 45.0,
    "2": 90.0,
    "3": 150.0,
    "4": 240.0,
    "entree": 60.0,
    "sortie": 30.0,
}

TENSION_VIGILANCE = 0.9
TENSION_HIGH = 1.0


@dataclass(frozen=True)
class CareMinutes:
    per_level: Mapping[int, float]
    admission: float
    discharge: float
    default_level: int = 2

    @classmethod
    def from_settings(cls, raw: Mapping[str, float] | None) -> CareMinutes:
        merged = {**DEFAULT_CARE_MINUTES, **(raw or {})}
        return cls(
            per_level={lvl: float(merged[str(lvl)]) for lvl in (1, 2, 3, 4)},
            admission=float(merged["entree"]),
            discharge=float(merged["sortie"]),
        )

    def of(self, level: int | None) -> float:
        return self.per_level.get(level or self.default_level, self.per_level[self.default_level])


@dataclass(frozen=True)
class Arrival:
    day: date
    care_level: int | None


@dataclass(frozen=True)
class WorkloadDay:
    day: date
    census_expected: float
    known_admissions: int
    expected_new_admissions: float
    care_minutes_expected: float
    care_minutes_p10: float
    care_minutes_p90: float
    staff_minutes: float | None
    load_ratio: float | None
    prob_over_capacity: float | None
    tension: str  # "inconnue" | "normale" | "vigilance" | "tension"


def admission_rate_by_weekday(
    stays: Sequence[StayRecord], as_of: date, weeks: int = 12
) -> dict[int, float]:
    """Mean admissions per weekday over the last ``weeks`` full weeks before ``as_of``."""
    start = as_of - timedelta(days=7 * weeks)
    counts: dict[int, int] = defaultdict(int)
    for s in stays:
        if start <= s.admission_date < as_of:
            counts[s.admission_date.weekday()] += 1
    return {wd: counts.get(wd, 0) / weeks for wd in range(7)}


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def tension_of(ratio: float | None) -> str:
    if ratio is None:
        return "inconnue"
    if ratio > TENSION_HIGH:
        return "tension"
    if ratio >= TENSION_VIGILANCE:
        return "vigilance"
    return "normale"


def forecast_workload(
    active_stays: Sequence[StayRecord],
    beds_open: int,
    as_of: date,
    horizon: int,
    model: HazardModel,
    minutes: CareMinutes,
    arrivals: Sequence[Arrival] = (),
    admission_rate: Mapping[int, float] | None = None,
    staff_minutes: Mapping[date, float] | None = None,
    plan_slip: Mapping[int, float] = DEFAULT_PLAN_SLIP,
) -> list[WorkloadDay]:
    rate = admission_rate or {}
    staff = staff_minutes or {}
    cdfs = [(s, discharge_cdf(s, as_of, horizon, model, plan_slip)) for s in active_stays]
    known_levels = [s.care_level for s in active_stays if s.care_level]
    mean_new = (
        sum(minutes.of(lvl) for lvl in known_levels) / len(known_levels)
        if known_levels
        else minutes.of(None)
    )
    by_day: dict[date, list[Arrival]] = defaultdict(list)
    for a in arrivals:
        by_day[max(a.day, as_of)].append(a)

    out: list[WorkloadDay] = []
    known_so_far: list[Arrival] = []
    new_cum = 0.0
    for k in range(horizon):
        day = as_of + timedelta(days=k)
        mean = 0.0
        var = 0.0
        census = 0.0
        discharges_expected = 0.0
        for stay, cdf in cdfs:
            prev = cdf[k - 1] if k > 0 else 0.0
            present = 1.0 - prev  # cared for at least part of the day
            leaving = cdf[k] - prev
            m = minutes.of(stay.care_level)
            mean += present * m + leaving * minutes.discharge
            if k == 0 and stay.admission_date == as_of:
                mean += minutes.admission
            var += present * (1 - present) * m * m + leaving * (1 - leaving) * minutes.discharge**2
            census += 1.0 - cdf[k]
            discharges_expected += cdf[k]
        today_known = by_day.get(day, [])
        known_so_far.extend(today_known)
        for a in known_so_far:
            mean += minutes.of(a.care_level)
        mean += len(today_known) * minutes.admission
        census += len(known_so_far)

        # Unknown admissions fill beds that are expected to be free, no more.
        expected_free = beds_open - census - new_cum
        unknown_today = 0.0
        if k > 0:
            unknown_today = max(0.0, rate.get(day.weekday(), 0.0) - len(today_known))
            unknown_today = max(0.0, min(unknown_today, expected_free))
        new_cum += unknown_today
        mean += new_cum * mean_new + unknown_today * minutes.admission
        var += new_cum * mean_new**2  # Poisson count of unknown admissions so far
        census += new_cum

        sd = math.sqrt(max(var, 0.0))
        staff_today = staff.get(day)
        ratio = round(mean / staff_today, 3) if staff_today else None
        over = (
            round(1.0 - _normal_cdf((staff_today - mean) / sd), 3)
            if staff_today and sd > 0
            else (None if not staff_today else float(mean > staff_today))
        )
        out.append(
            WorkloadDay(
                day=day,
                census_expected=round(census, 2),
                known_admissions=len(today_known),
                expected_new_admissions=round(unknown_today, 2),
                care_minutes_expected=round(mean, 1),
                care_minutes_p10=round(max(0.0, mean - Z_80 * sd), 1),
                care_minutes_p90=round(mean + Z_80 * sd, 1),
                staff_minutes=staff_today,
                load_ratio=ratio,
                prob_over_capacity=over,
                tension=tension_of(ratio),
            )
        )
    return out


def realized_care_minutes(stays: Sequence[StayRecord], day: date, minutes: CareMinutes) -> float:
    """Care minutes that the census of ``day`` actually required (same rules as the forecast)."""
    total = 0.0
    for s in stays:
        if s.admission_date > day:
            continue
        if s.discharge_date is not None and s.discharge_date < day:
            continue
        total += minutes.of(s.care_level)
        if s.admission_date == day:
            total += minutes.admission
        if s.discharge_date == day:
            total += minutes.discharge
    return total


@dataclass(frozen=True)
class WorkloadBacktest:
    points: list[tuple[date, int, float, float, float, float]]  # as_of, k, mean, p10, p90, actual
    mape: float | None
    bias_pct: float | None
    coverage_80: float | None


def backtest_workload(
    stays: Sequence[StayRecord],
    beds_open: int,
    as_of_dates: Sequence[date],
    today: date,
    minutes: CareMinutes,
    model_for: Callable[[date], HazardModel],
    horizon: int = 7,
) -> WorkloadBacktest:
    """Replay the workload forecast for one pool at past dates (no plans, no promises).

    ``model_for`` returns the length-of-stay model fitted with data known at a
    date, so the caller decides which stays it uses (usually the whole group).
    Admissions of the replayed day itself count as known that morning, as they
    are in live use (they are planned the day before).
    """
    points: list[tuple[date, int, float, float, float, float]] = []
    for as_of in as_of_dates:
        if as_of + timedelta(days=horizon - 1) >= today:
            continue
        model = model_for(as_of)
        active = [
            StayRecord(s.stay_id, s.site_id, s.mention, s.admission_date, None, None, s.care_level)
            for s in stays
            if s.admission_date <= as_of and (s.discharge_date is None or s.discharge_date >= as_of)
        ]
        if not active:
            continue
        rate = admission_rate_by_weekday(stays, as_of)
        days = forecast_workload(active, beds_open, as_of, horizon, model, minutes, (), rate)
        for k, d in enumerate(days):
            actual = realized_care_minutes(stays, d.day, minutes)
            points.append(
                (as_of, k, d.care_minutes_expected, d.care_minutes_p10, d.care_minutes_p90, actual)
            )
    useful = [p for p in points if p[5] > 0]
    if not useful:
        return WorkloadBacktest(points, None, None, None)
    n = len(useful)
    mape = sum(abs(p[2] - p[5]) / p[5] for p in useful) / n
    bias = sum((p[2] - p[5]) / p[5] for p in useful) / n
    coverage = sum(1 for p in useful if p[3] <= p[5] <= p[4]) / n
    return WorkloadBacktest(points, round(mape, 4), round(bias, 4), round(coverage, 3))
