"""The engine's emergency series use the single definition of domain/ed.py (T-2, T-14)."""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from services.admissions_smr.domain.ed import Visit, boarding_10h, census
from services.forecast_engine.data import EdRow, History, SiteRef, _fill_series

PARIS = ZoneInfo("Europe/Paris")
# Both daylight-saving changes of 2026: 29 March (02:00 → 03:00), 25 October (03:00 → 02:00).
DST_DAYS = (date(2026, 3, 29), date(2026, 10, 25))


def random_visits(seed: int, around: date, n: int = 400) -> list[Visit]:
    """Visits on a 30-minute grid (so 08:00, 10:00 and 72 h boundaries are hit exactly)."""
    rng = random.Random(seed)
    start = datetime.combine(around - timedelta(days=5), datetime.min.time(), tzinfo=UTC)
    slots = 10 * 48
    out = []
    for _ in range(n):
        arrived = start + timedelta(minutes=30 * rng.randrange(slots))
        decision = (
            None if rng.random() < 0.35 else arrived + timedelta(minutes=30 * rng.randrange(-2, 60))
        )
        left = None if rng.random() < 0.2 else arrived + timedelta(minutes=30 * rng.randrange(200))
        out.append(Visit(arrived, decision, left))
    return out


def history_of(visits: list[Visit], first: date, last: date) -> History:
    ed = [EdRow(1, v.arrived_at, v.admit_decision_at, v.left_at, None, 7) for v in visits]
    h = History(1, PARIS, first, last, {1: SiteRef(1, "Site", None, None)}, {}, [], ed, {})
    _fill_series(h, [])
    return h


@pytest.mark.parametrize("around", DST_DAYS)
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_engine_boarding_series_equals_the_domain_count(around: date, seed: int) -> None:
    visits = random_visits(seed, around)
    first, last = around - timedelta(days=5), around + timedelta(days=6)
    days = [first + timedelta(days=k) for k in range((last - first).days + 1)]

    h = history_of(visits, first, last)

    assert h.site_series["boarding_10h"][1].tolist() == [
        boarding_10h(visits, d, PARIS) for d in days
    ]


@pytest.mark.parametrize("around", DST_DAYS)
@pytest.mark.parametrize("seed", [4, 5])
def test_engine_waiting_patients_equal_the_domain_census(around: date, seed: int) -> None:
    visits = random_visits(seed, around)
    h = history_of(visits, around - timedelta(days=5), around + timedelta(days=6))
    start = datetime.combine(around - timedelta(days=5), datetime.min.time(), tzinfo=UTC)

    for k in range(0, 11 * 48, 3):  # every 90 minutes, on and between the grid points
        t = start + timedelta(minutes=30 * k)
        assert h.ed_waiting(t)[7] == census(visits, t).waiting_bed, t


def test_series_follow_local_days_across_the_clock_changes() -> None:
    """Arrivals at 00:30 local on a change day belong to that day, not to the UTC one."""

    def paris(day: date, hour: int, minute: int = 0) -> datetime:
        return datetime(day.year, day.month, day.day, hour, minute, tzinfo=PARIS).astimezone(UTC)

    spring, autumn = DST_DAYS
    visits = [
        Visit(paris(spring, 0, 30), None, paris(spring, 4)),  # 23:30 UTC the day before
        # Arrived 07:30 on the spring day (05:30 UTC), decided at 09:00: boards at 10:00 local,
        # which is 08:00 UTC that day.
        Visit(paris(spring, 7, 30), paris(spring, 9), paris(spring, 10, 1)),
        Visit(paris(autumn, 0, 30), None, paris(autumn, 4)),  # 22:30 UTC the day before
        # Left at 09:30 local on the autumn day (08:30 UTC): gone at 10:00 local (09:00 UTC).
        Visit(paris(autumn, 1), paris(autumn, 2), paris(autumn, 9, 30)),
    ]
    first, last = spring - timedelta(days=1), autumn + timedelta(days=1)

    h = history_of(visits, first, last)

    arrivals = h.site_series["ed_arrivals"][1]
    boarding = h.site_series["boarding_10h"][1]
    assert arrivals[h.index(spring)] == 2 and arrivals[h.index(spring - timedelta(days=1))] == 0
    assert arrivals[h.index(autumn)] == 2 and arrivals[h.index(autumn - timedelta(days=1))] == 0
    assert boarding[h.index(spring)] == 1
    assert boarding[h.index(autumn)] == 0
    assert boarding.sum() == 1
