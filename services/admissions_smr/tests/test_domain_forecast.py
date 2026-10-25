from __future__ import annotations

from datetime import date, timedelta

import pytest

from services.admissions_smr.domain.forecast import (
    StayRecord,
    backtest,
    discharge_cdf,
    fit_hazard,
    forecast_pool,
    poisson_binomial,
    prob_at_least,
    quantile,
)

TODAY = date(2026, 10, 25)


def stays_with_fixed_los(
    n: int, los: int, mention: str = "geriatrie", end: date = TODAY
) -> list[StayRecord]:
    out = []
    for i in range(n):
        admit = end - timedelta(days=200 + i)
        out.append(StayRecord(i, 1, mention, admit, admit + timedelta(days=los)))
    return out


def test_poisson_binomial_matches_binomial_and_sums_to_one() -> None:
    dist = poisson_binomial([0.5, 0.5, 0.5])
    assert dist == pytest.approx([0.125, 0.375, 0.375, 0.125])
    assert sum(poisson_binomial([0.1, 0.9, 0.33, 0.7])) == pytest.approx(1.0)
    assert quantile(dist, 0.5) == 1
    assert prob_at_least(dist, 0) == 1.0
    assert prob_at_least(dist, 3) == pytest.approx(0.125)


def test_fixed_los_gives_a_sharp_discharge_day() -> None:
    model = fit_hazard(stays_with_fixed_los(50, 10), TODAY)
    stay = StayRecord(999, 1, "geriatrie", TODAY - timedelta(days=7))
    cdf = discharge_cdf(stay, TODAY, 7, model)
    # LOS is always 10 days: discharge exactly 3 days from today.
    assert cdf[2] == pytest.approx(0.0)
    assert cdf[3] == pytest.approx(1.0)


def test_censored_stays_are_not_counted_as_discharges() -> None:
    # 30 short stays (LOS 5) and 30 long stays still present after 40 days.
    short = stays_with_fixed_los(30, 5)
    long_present = [
        StayRecord(100 + i, 1, "geriatrie", TODAY - timedelta(days=40 + i)) for i in range(30)
    ]
    model = fit_hazard(short + long_present, TODAY)
    # A naive model using completed stays only would say every stay leaves at day 5.
    # With censoring, half of the cohort is known to be still there at day 40.
    assert model.hazard("geriatrie", 5) == pytest.approx(0.5)
    assert model.hazard("geriatrie", 6) == pytest.approx(0.0)


def test_hazard_ignores_information_after_as_of() -> None:
    as_of = TODAY - timedelta(days=30)
    future = [
        StayRecord(i, 1, "neuro", as_of + timedelta(days=1), as_of + timedelta(days=3))
        for i in range(40)
    ]
    model = fit_hazard(future, as_of)
    assert model.n_stays == {}


def test_low_data_mention_falls_back_to_pooled_then_tail() -> None:
    pooled = stays_with_fixed_los(60, 10, "geriatrie")
    model = fit_hazard(pooled, TODAY)
    # "cardio" has no data: it uses the pooled hazard at day 10 ...
    assert model.hazard("cardio", 10) == pytest.approx(1.0)
    # ... and the tail hazard beyond what the pool can support.
    assert model.hazard("cardio", 300) == pytest.approx(model.tail_hazard)


def test_planned_date_drives_the_cdf_with_slip_prior() -> None:
    model = fit_hazard(stays_with_fixed_los(50, 30), TODAY)
    stay = StayRecord(1, 1, "geriatrie", TODAY - timedelta(days=3), None, TODAY + timedelta(days=2))
    cdf = discharge_cdf(stay, TODAY, 14, model, plan_slip={0: 0.5, 1: 0.5})
    assert cdf[1] == pytest.approx(0.0)
    assert cdf[2] == pytest.approx(0.5)
    assert cdf[3] == pytest.approx(1.0)


def test_overdue_planned_date_is_ignored() -> None:
    model = fit_hazard(stays_with_fixed_los(50, 10), TODAY)
    stay = StayRecord(1, 1, "geriatrie", TODAY - timedelta(days=7), None, TODAY - timedelta(days=1))
    assert discharge_cdf(stay, TODAY, 7, model) == discharge_cdf(
        StayRecord(1, 1, "geriatrie", TODAY - timedelta(days=7)), TODAY, 7, model
    )


def test_forecast_pool_free_beds_and_reservations() -> None:
    model = fit_hazard(stays_with_fixed_los(50, 10), TODAY)
    active = [StayRecord(i, 1, "geriatrie", TODAY - timedelta(days=8)) for i in range(5)]
    fc = forecast_pool(
        active,
        beds_open=6,
        as_of=TODAY,
        horizon=4,
        model=model,
        reservations={TODAY + timedelta(days=1): 1},
    )
    day0, day1, day2 = fc.days[0], fc.days[1], fc.days[2]
    assert fc.occupied_now == 5
    assert day0.free_expected == pytest.approx(1.0)  # 6 open - 5 occupied, nobody leaves
    assert day1.reserved == 1
    assert day1.free_expected == pytest.approx(0.0)  # one bed promised
    assert day2.cumulative_expected == pytest.approx(5.0)  # all leave on LOS day 10
    assert day2.free_expected == pytest.approx(5.0)
    assert day2.prob_at_least_one_free == pytest.approx(1.0)
    assert day1.prob_at_least_one_free == pytest.approx(0.0)


def test_backtest_uses_only_past_data_and_reports_coverage() -> None:
    stays = []
    for i in range(400):
        admit = TODAY - timedelta(days=400 - i)
        stays.append(StayRecord(i, 1, "geriatrie", admit, admit + timedelta(days=10 + (i % 7))))
    dates = [TODAY - timedelta(days=60 - 7 * k) for k in range(8)]
    result = backtest(stays, dates, TODAY, horizon=7)
    assert result.points
    assert all(p.as_of + timedelta(days=6) < TODAY for p in result.points)
    assert result.mae is not None and result.mae < 3
    assert result.coverage_80 is not None
