"""Discharge forecast and bed availability, J+0 to J+H.

Method (deliberately simple, inspectable and calibratable):

1. Length of stay (LOS) is modelled per SMR mention with a discrete-time
   Kaplan-Meier hazard. Stays still in the unit are right-censored, so long
   stays are not under-represented. Where fewer than ``min_at_risk`` stays are
   at risk at a given LOS, the hazard falls back to all mentions pooled, then
   to a constant tail hazard.
2. A stay with a planned discharge date that is today or later follows that
   date shifted by a slip distribution: measured from the history of planned
   dates once at least ``MIN_SLIP_SAMPLES`` discharges can be compared with the
   plan known beforehand, a stated prior until then.
3. For each day, the number of discharges by the end of that day is a sum of
   independent Bernoulli variables (Poisson-binomial); its distribution is
   computed exactly, which gives intervals for discharges and free beds.

Census convention: a stay occupies a bed at the end of day ``d`` when
``admission_date <= d`` and it is not discharged on or before ``d``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

DEFAULT_MIN_AT_RISK = 20
DEFAULT_TAIL_HAZARD = 1.0 / 30.0
MAX_LOS_DAYS = 365

# Prior on (actual discharge - planned discharge), in days, used until measured.
DEFAULT_PLAN_SLIP: Mapping[int, float] = {0: 0.6, 1: 0.15, 2: 0.1, 3: 0.05, 5: 0.05, 7: 0.05}
MIN_SLIP_SAMPLES = 30
SLIP_RANGE = (-7, 21)


@dataclass(frozen=True)
class StayRecord:
    """Minimal view of a stay for forecasting and metrics."""

    stay_id: int
    site_id: int
    mention: str
    admission_date: date
    discharge_date: date | None = None
    planned_discharge_date: date | None = None
    care_level: int | None = None


@dataclass(frozen=True)
class PlanSlip:
    """Distribution of (actual discharge - plan known beforehand), in days."""

    weights: Mapping[int, float]
    samples: int
    measured: bool


PlanHistory = Mapping[int, Sequence[tuple[date, date | None]]]
"""Per stay id: (day the plan was recorded, planned discharge date or None if cleared)."""


def plan_known_at(history: Sequence[tuple[date, date | None]], as_of: date) -> date | None:
    """Latest plan recorded strictly before ``as_of`` (what the team knew that morning)."""
    known: date | None = None
    for recorded_on, planned in sorted(history, key=lambda h: h[0]):
        if recorded_on < as_of:
            known = planned
    return known


def estimate_plan_slip(
    stays: Iterable[StayRecord], history: PlanHistory, as_of: date, lead_days: int = 1
) -> PlanSlip:
    """Measure the slip on stays discharged before ``as_of``.

    For each discharged stay, the plan used is the latest one recorded at least
    ``lead_days`` before the actual discharge: a plan typed on the day of the
    discharge says nothing about the forecasting ability of the teams.
    """
    counts: dict[int, int] = defaultdict(int)
    n = 0
    for stay in stays:
        if stay.discharge_date is None or stay.discharge_date >= as_of:
            continue
        plan = plan_known_at(
            history.get(stay.stay_id, ()), stay.discharge_date - timedelta(days=lead_days - 1)
        )
        if plan is None:
            continue
        slip = (stay.discharge_date - plan).days
        slip = max(SLIP_RANGE[0], min(SLIP_RANGE[1], slip))
        counts[slip] += 1
        n += 1
    if n < MIN_SLIP_SAMPLES:
        return PlanSlip(DEFAULT_PLAN_SLIP, n, False)
    return PlanSlip({k: v / n for k, v in sorted(counts.items())}, n, True)


ELAPSED_BANDS = (7, 14, 28, 56, 10_000)
LANDMARK_HORIZON = 28
LANDMARK_WEEKS = 52
MIN_LANDMARK_SAMPLES = 40


def elapsed_band(elapsed: int) -> int:
    return next(i for i, upper in enumerate(ELAPSED_BANDS) if elapsed <= upper)


@dataclass
class LandmarkModel:
    """P(discharge on day k after a morning | no plan known that morning, mention, time spent).

    Estimated on past mornings ("landmarks") whose outcome over ``horizon`` days
    is fully known. Needed because teams enter a planned date mostly when the
    discharge is near: patients without a plan leave less often than the
    overall length-of-stay curve suggests.
    """

    horizon: int
    pmf: dict[tuple[str, int], list[float]]
    samples: dict[tuple[str, int], int]

    def cdf(self, mention: str, elapsed: int, horizon: int) -> list[float] | None:
        if horizon > self.horizon:
            return None
        band = elapsed_band(elapsed)
        for key in ((mention, band), ("*", band)):
            if self.samples.get(key, 0) >= MIN_LANDMARK_SAMPLES:
                acc = 0.0
                out = []
                for k in range(horizon):
                    acc += self.pmf[key][k]
                    out.append(min(1.0, acc))
                return out
        return None


def fit_landmarks(
    stays: Sequence[StayRecord],
    plans: PlanHistory,
    as_of: date,
    horizon: int = LANDMARK_HORIZON,
    weeks: int = LANDMARK_WEEKS,
) -> LandmarkModel:
    counts: dict[tuple[str, int], list[int]] = defaultdict(lambda: [0] * horizon)
    samples: dict[tuple[str, int], int] = defaultdict(int)
    # "No plan" only means something once teams were entering plans: landmarks start
    # two weeks after the first recorded plan.
    recorded = [day for history in plans.values() for day, _ in history if day < as_of]
    if not recorded:
        return LandmarkModel(horizon, {}, {})
    plans_start = min(recorded) + timedelta(days=14)
    first = as_of - timedelta(days=horizon + 7 * (weeks - 1))
    last = as_of - timedelta(days=horizon)
    window = [
        s
        for s in stays
        if s.admission_date <= last and (s.discharge_date is None or s.discharge_date >= first)
    ]
    for j in range(weeks):
        landmark = as_of - timedelta(days=horizon + 7 * j)
        if landmark < plans_start:
            break
        for s in window:
            if s.admission_date > landmark:
                continue
            if s.discharge_date is not None and s.discharge_date < landmark:
                continue
            plan = plan_known_at(plans.get(s.stay_id, ()), landmark)
            if plan is not None and plan >= landmark:
                continue  # had a usable plan that morning: covered by the slip model
            band = elapsed_band((landmark - s.admission_date).days)
            for key in ((s.mention, band), ("*", band)):
                samples[key] += 1
                if s.discharge_date is not None:
                    k = (s.discharge_date - landmark).days
                    if k < horizon:
                        counts[key][k] += 1
    pmf = {key: [c / samples[key] for c in counts[key]] for key in samples}
    return LandmarkModel(horizon, pmf, dict(samples))


@dataclass
class HazardModel:
    by_mention: dict[str, list[float | None]]
    pooled: list[float | None]
    tail_hazard: float
    n_stays: dict[str, int] = field(default_factory=dict)
    n_completed: dict[str, int] = field(default_factory=dict)
    landmarks: LandmarkModel | None = None

    def hazard(self, mention: str, t: int) -> float:
        own = self.by_mention.get(mention)
        if own is not None and t < len(own) and own[t] is not None:
            return own[t]  # type: ignore[return-value]
        if t < len(self.pooled) and self.pooled[t] is not None:
            return self.pooled[t]  # type: ignore[return-value]
        return self.tail_hazard


def fit_hazard(
    stays: Iterable[StayRecord],
    as_of: date,
    min_at_risk: int = DEFAULT_MIN_AT_RISK,
    plans: PlanHistory | None = None,
) -> HazardModel:
    """Fit discrete-time LOS hazards using only information available at ``as_of``.

    A stay discharged on or after ``as_of`` (or not discharged) is censored at
    ``as_of - admission_date``: it is known to be at risk for t < that value.
    Stays admitted on or after ``as_of`` are ignored.
    """
    events: dict[str, list[int]] = defaultdict(lambda: [0] * (MAX_LOS_DAYS + 1))
    at_risk: dict[str, list[int]] = defaultdict(lambda: [0] * (MAX_LOS_DAYS + 2))
    n_stays: dict[str, int] = defaultdict(int)
    n_completed: dict[str, int] = defaultdict(int)

    stays = list(stays)
    for stay in stays:
        if stay.admission_date >= as_of:
            continue
        n_stays[stay.mention] += 1
        if stay.discharge_date is not None and stay.discharge_date < as_of:
            los = min((stay.discharge_date - stay.admission_date).days, MAX_LOS_DAYS)
            events[stay.mention][los] += 1
            _add_range(at_risk[stay.mention], 0, los + 1)  # at risk for t = 0..los
            n_completed[stay.mention] += 1
        else:
            censored_at = min((as_of - stay.admission_date).days, MAX_LOS_DAYS)
            _add_range(at_risk[stay.mention], 0, censored_at)  # at risk for t < censored_at

    pooled_events = [0] * (MAX_LOS_DAYS + 1)
    pooled_risk = [0] * (MAX_LOS_DAYS + 2)
    for mention in at_risk:
        for t in range(MAX_LOS_DAYS + 1):
            pooled_events[t] += events[mention][t]
            pooled_risk[t] += at_risk[mention][t]

    def hazards(ev: list[int], risk: list[int]) -> list[float | None]:
        out: list[float | None] = []
        for t in range(MAX_LOS_DAYS + 1):
            out.append(ev[t] / risk[t] if risk[t] >= min_at_risk else None)
        return out

    by_mention = {m: hazards(events[m], at_risk[m]) for m in at_risk}
    pooled = hazards(pooled_events, pooled_risk)

    # Tail hazard: events / exposure where the pooled estimate is no longer reliable.
    tail_events = 0
    tail_exposure = 0
    for t in range(MAX_LOS_DAYS + 1):
        if pooled[t] is None:
            tail_events += pooled_events[t]
            tail_exposure += pooled_risk[t]
    tail = tail_events / tail_exposure if tail_events >= 5 and tail_exposure > 0 else 0.0
    tail_hazard = tail if tail > 0 else DEFAULT_TAIL_HAZARD

    return HazardModel(
        by_mention=by_mention,
        pooled=pooled,
        tail_hazard=tail_hazard,
        n_stays=dict(n_stays),
        n_completed=dict(n_completed),
        landmarks=fit_landmarks(stays, plans, as_of) if plans else None,
    )


def _add_range(arr: list[int], start: int, stop: int) -> None:
    for t in range(start, max(start, stop)):
        arr[t] += 1


def discharge_cdf(
    stay: StayRecord,
    as_of: date,
    horizon: int,
    model: HazardModel,
    plan_slip: Mapping[int, float] = DEFAULT_PLAN_SLIP,
) -> list[float]:
    """P(stay discharged by the end of day as_of + k), k = 0..horizon-1.

    The stay is assumed present at the start of ``as_of``.
    """
    elapsed = max(0, (as_of - stay.admission_date).days)
    planned = stay.planned_discharge_date
    if planned is not None and planned >= as_of:
        pmf = [0.0] * horizon
        total = 0.0
        for slip, weight in plan_slip.items():
            # A plan that slips "into the past" means the patient leaves today.
            day = max(0, (planned - as_of).days + slip)
            total += weight
            if day < horizon:
                pmf[day] += weight
        cdf: list[float] = []
        acc = 0.0
        for k in range(horizon):
            acc += pmf[k] / total if total > 0 else 0.0
            cdf.append(min(1.0, acc))
        return cdf

    if model.landmarks is not None:
        conditional = model.landmarks.cdf(stay.mention, elapsed, horizon)
        if conditional is not None:
            return conditional

    cdf = []
    survive = 1.0
    for k in range(horizon):
        h = model.hazard(stay.mention, elapsed + k)
        survive *= 1.0 - h
        cdf.append(1.0 - survive)
    return cdf


def poisson_binomial(probs: Sequence[float]) -> list[float]:
    """Exact distribution of the number of successes of independent Bernoullis."""
    dist = [1.0]
    for p in probs:
        p = min(1.0, max(0.0, p))
        nxt = [0.0] * (len(dist) + 1)
        for i, mass in enumerate(dist):
            if mass == 0.0:
                continue
            nxt[i] += mass * (1.0 - p)
            nxt[i + 1] += mass * p
        dist = nxt
    return dist


def quantile(dist: Sequence[float], q: float) -> int:
    acc = 0.0
    for i, mass in enumerate(dist):
        acc += mass
        if acc >= q - 1e-12:
            return i
    return len(dist) - 1


def prob_at_least(dist: Sequence[float], k: int) -> float:
    if k <= 0:
        return 1.0
    return float(min(1.0, max(0.0, sum(dist[k:]))))


@dataclass(frozen=True)
class DayForecast:
    day: date
    expected_discharges: float
    cumulative_expected: float
    cumulative_p10: int
    cumulative_p90: int
    reserved: int
    free_expected: float
    free_p10: int
    free_p90: int
    prob_at_least_one_free: float


@dataclass(frozen=True)
class PoolForecast:
    beds_open: int
    occupied_now: int
    days: list[DayForecast]


def forecast_pool(
    active_stays: Sequence[StayRecord],
    beds_open: int,
    as_of: date,
    horizon: int,
    model: HazardModel,
    reservations: Mapping[date, int] | None = None,
    plan_slip: Mapping[int, float] = DEFAULT_PLAN_SLIP,
) -> PoolForecast:
    """Discharges and free beds per day for one pool (site x mention).

    ``reservations`` maps an expected admission date to the number of beds
    already promised that day (accords and confirmations).
    """
    reservations = reservations or {}
    cdfs = [discharge_cdf(s, as_of, horizon, model, plan_slip) for s in active_stays]
    occupied = len(active_stays)
    base_free = beds_open - occupied
    days: list[DayForecast] = []
    previous_cum = 0.0
    reserved_cum = sum(n for d, n in reservations.items() if d < as_of)
    for k in range(horizon):
        day = as_of + timedelta(days=k)
        reserved_cum += reservations.get(day, 0)
        probs = [cdf[k] for cdf in cdfs]
        dist = poisson_binomial(probs)
        cum_expected = sum(probs)
        offset = base_free - reserved_cum
        days.append(
            DayForecast(
                day=day,
                expected_discharges=round(cum_expected - previous_cum, 3),
                cumulative_expected=round(cum_expected, 3),
                cumulative_p10=quantile(dist, 0.1),
                cumulative_p90=quantile(dist, 0.9),
                reserved=reserved_cum,
                free_expected=round(offset + cum_expected, 3),
                free_p10=offset + quantile(dist, 0.1),
                free_p90=offset + quantile(dist, 0.9),
                prob_at_least_one_free=round(prob_at_least(dist, 1 - offset), 4),
            )
        )
        previous_cum = cum_expected
    return PoolForecast(beds_open=beds_open, occupied_now=occupied, days=days)


@dataclass(frozen=True)
class StayOutlook:
    stay_id: int
    prob_within_7_days: float
    median_discharge_day: date | None  # None = beyond the horizon


def stay_outlook(
    stay: StayRecord,
    as_of: date,
    model: HazardModel,
    horizon: int = 28,
    plan_slip: Mapping[int, float] = DEFAULT_PLAN_SLIP,
) -> StayOutlook:
    cdf = discharge_cdf(stay, as_of, horizon, model, plan_slip)
    median = next((as_of + timedelta(days=k) for k, p in enumerate(cdf) if p >= 0.5), None)
    return StayOutlook(
        stay_id=stay.stay_id,
        prob_within_7_days=round(cdf[min(6, horizon - 1)], 4),
        median_discharge_day=median,
    )


@dataclass(frozen=True)
class BacktestPoint:
    as_of: date
    predicted: float
    p10: int
    p90: int
    actual: int


@dataclass(frozen=True)
class BacktestResult:
    horizon_days: int
    points: list[BacktestPoint]
    mae: float | None
    bias: float | None
    coverage_80: float | None


def backtest(
    stays: Sequence[StayRecord],
    as_of_dates: Iterable[date],
    today: date,
    horizon: int = 7,
    plans: PlanHistory | None = None,
) -> BacktestResult:
    """Replay the forecast at past dates using only data known at each date.

    When ``plans`` is given, each stay uses the planned discharge date known
    the morning of the replayed date, and the slip distribution is measured on
    discharges before that date. Without it, the LOS model alone is measured.
    """
    points: list[BacktestPoint] = []
    for as_of in as_of_dates:
        end = as_of + timedelta(days=horizon - 1)
        if end >= today:
            continue
        model = fit_hazard(stays, as_of, plans=plans)
        slip = estimate_plan_slip(stays, plans, as_of).weights if plans else DEFAULT_PLAN_SLIP
        active = [
            StayRecord(
                s.stay_id,
                s.site_id,
                s.mention,
                s.admission_date,
                None,
                plan_known_at(plans.get(s.stay_id, ()), as_of) if plans else None,
            )
            for s in stays
            if s.admission_date < as_of and (s.discharge_date is None or s.discharge_date >= as_of)
        ]
        if not active:
            continue
        actual = sum(
            1
            for s in stays
            if s.admission_date < as_of
            and s.discharge_date is not None
            and as_of <= s.discharge_date <= end
        )
        probs = [discharge_cdf(s, as_of, horizon, model, slip)[horizon - 1] for s in active]
        dist = poisson_binomial(probs)
        points.append(
            BacktestPoint(
                as_of=as_of,
                predicted=round(sum(probs), 2),
                p10=quantile(dist, 0.1),
                p90=quantile(dist, 0.9),
                actual=actual,
            )
        )
    if not points:
        return BacktestResult(horizon, points, None, None, None)
    n = len(points)
    mae = sum(abs(p.predicted - p.actual) for p in points) / n
    bias = sum(p.predicted - p.actual for p in points) / n
    coverage = sum(1 for p in points if p.p10 <= p.actual <= p.p90) / n
    return BacktestResult(horizon, points, round(mae, 3), round(bias, 3), round(coverage, 3))
