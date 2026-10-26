from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta

import pytest

from services.admissions_smr.domain.forecast import StayRecord
from services.admissions_smr.domain.metrics import (
    CapacityPoint,
    PoolCapacity,
    PoolSeries,
    RequestRecord,
    daily_capacity,
    daily_occupancy,
    date_range,
    north_star,
    pool_capacity,
    summarise_requests,
)

D0 = date(2026, 1, 1)


def test_census_convention_counts_end_of_day_presence() -> None:
    stays = [
        StayRecord(1, 1, "g", D0, D0 + timedelta(days=2)),  # present end of D0, D0+1
        StayRecord(2, 1, "g", D0 + timedelta(days=1), None),  # present from D0+1
    ]
    occ = daily_occupancy(stays, D0, D0 + timedelta(days=3))
    assert [occ[d] for d in date_range(D0, D0 + timedelta(days=3))] == [1, 2, 1, 1]


def test_capacity_history_by_pool_and_closed_beds_by_reason() -> None:
    current = [PoolCapacity(1, "g", 40, 36), PoolCapacity(1, "p", 20, 20)]
    changes = [
        CapacityPoint(1, "g", D0, 40, 40, "ouverture"),
        CapacityPoint(1, "g", D0 + timedelta(days=2), 40, 36, "personnel"),
    ]
    per_pool = pool_capacity(changes, current, D0, D0 + timedelta(days=3))
    assert per_pool[(1, "g")][D0 + timedelta(days=1)][1] == 40
    assert per_pool[(1, "g")][D0 + timedelta(days=2)][1] == 36
    assert per_pool[(1, "p")][D0][1] == 20  # no history: current value
    total = daily_capacity(changes, current, D0, D0 + timedelta(days=3))
    assert total[D0 + timedelta(days=3)] == (60, 56, {"personnel": 4})


def test_request_summary_response_times_and_conversion() -> None:
    t = datetime(2026, 1, 5, 9, tzinfo=UTC)
    reqs = [
        RequestRecord(1, t, "admise", t + timedelta(hours=10), None, None, True),
        RequestRecord(2, t, "perdue", t + timedelta(hours=30), None, "autre_etablissement", True),
        RequestRecord(3, t, "refusee", t + timedelta(hours=2), "pas_de_lit", None, False),
        RequestRecord(4, t, "nouvelle", None, None, None, False),
    ]
    s = summarise_requests(reqs)
    assert s.received == 4 and s.responded == 3
    assert s.response_hours_median == 10.0
    assert s.responded_within_24h == pytest.approx(2 / 3, abs=1e-3)
    assert s.conversion_rate == 0.25
    assert s.lost_after_accord_rate == 0.5
    assert s.refusal_reasons == {"pas_de_lit": 1}


def _ar_series(
    rng: random.Random,
    days: list[date],
    beds: int,
    level: float,
    shift_from: date | None,
    shift: float,
) -> dict[date, int]:
    """Autocorrelated census around ``level`` beds, optionally shifted after a date."""
    x = 0.0
    out = {}
    for d in days:
        x = 0.97 * x + rng.gauss(0, 0.6)
        target = level + (shift if shift_from and d >= shift_from else 0.0)
        out[d] = max(0, min(beds, round(target + x)))
    return out


def _series(
    seed: int, shift: float, history_days: int = 1000
) -> tuple[list[PoolSeries], tuple[date, date], tuple[date, date], date]:
    rng = random.Random(seed)
    start = D0
    days = date_range(start, start + timedelta(days=history_days - 1))
    period = (days[-112], days[-1])
    baseline = (days[-112 - 30 - 120], days[-112 - 31])
    pools = [
        PoolSeries(
            f"p{k}", _ar_series(rng, days, 30, 26.0, period[0], shift), dict.fromkeys(days, 30)
        )
        for k in range(6)
    ]
    return pools, baseline, period, start


def test_north_star_excludes_pools_whose_capacity_changed() -> None:
    pools, baseline, period, start = _series(1, 0.0)
    changed = PoolSeries(
        "fermeture",
        pools[0].occupied,
        {d: (40 if d < period[0] else 36) for d in pools[0].open_beds},
    )
    ns = north_star([*pools, changed], baseline, period, 150.0, 0.15, start)
    assert ns is not None
    assert "fermeture" in ns.excluded_pools
    assert "fermeture" not in ns.included_pools


def test_north_star_detects_a_real_effect_and_triggers_the_fee() -> None:
    pools, baseline, period, start = _series(2, shift=2.0)  # +2 occupied beds per pool
    ns = north_star(pools, baseline, period, 150.0, 0.15, start)
    assert ns is not None and ns.recovered_low is not None
    expected = 6 * 2.0 * 112
    assert ns.recovered_low > 0
    # Before/after on autocorrelated census is noisy even with a real effect.
    assert ns.recovered_bed_days == pytest.approx(expected, rel=0.5)
    assert ns.success_fee_eur == pytest.approx(ns.recovered_bed_days * 150 * 0.15, rel=0.01)


def test_north_star_rarely_triggers_a_fee_without_effect() -> None:
    # This AR(1) generator is harsher than seed.py (8/60 false fees vs 2-7 % there):
    # the rate depends on the process, hence re-measurement on real history.
    fees = 0
    for seed in range(60):
        pools, baseline, period, start = _series(100 + seed, shift=0.0)
        ns = north_star(pools, baseline, period, 150.0, 0.15, start)
        assert ns is not None
        fees += ns.success_fee_eur > 0
    assert fees <= 9


def test_north_star_gives_no_interval_without_enough_history() -> None:
    pools, baseline, period, start = _series(3, shift=5.0, history_days=420)
    ns = north_star(pools, baseline, period, 150.0, 0.15, start)
    assert ns is not None
    assert ns.recovered_low is None and ns.recovered_high is None
    assert ns.success_fee_eur == 0.0
    assert "Historique insuffisant" in ns.interval_note


def test_north_star_requires_period_after_baseline() -> None:
    pools, baseline, _, start = _series(4, 0.0)
    assert north_star(pools, baseline, baseline, 150.0, 0.15, start) is None
