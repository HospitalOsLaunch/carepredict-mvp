"""Monte Carlo of available beds: invariants, promises, aggregation and tension."""

from __future__ import annotations

import numpy as np
import pytest

from services.admissions_smr.domain.ror import TENSION_NORMAL_MIN
from services.forecast_engine.capacity import (
    UnitInputs,
    aggregate,
    common_shock_variance,
    gamma_factor,
    nb_size,
    sample_counts,
    simulate_unit,
    summarise,
    tension_probabilities,
    weekday_retention,
)

DAYS = 8


def unit(**overrides: object) -> UnitInputs:
    base: dict[str, object] = {
        "key": 1,
        "installed": [20] * DAYS,
        "open_beds": [20] * DAYS,
        "occupied": 18,
        "discharge_cdfs": np.tile(np.linspace(0.15, 0.8, DAYS), (18, 1)),
        "new_stay_cdf": np.linspace(0.05, 0.7, DAYS),
        "promised_cum": [0] * DAYS,
        "arrivals_centre": [3.0] * DAYS,
        "arrivals_q10": [1.0] * DAYS,
        "arrivals_q90": [6.0] * DAYS,
    }
    base.update(overrides)
    return UnitInputs(**base)  # type: ignore[arg-type]


def test_nb_size_is_poisson_when_the_interval_is_not_wider_than_poisson() -> None:
    assert nb_size(10.0, 6.0, 14.0) == float("inf")  # Poisson(10): q10 6, q90 14
    assert nb_size(0.0, 0.0, 3.0) == float("inf")


def test_sampled_counts_match_the_centre_and_the_interval() -> None:
    rng = np.random.default_rng(0)

    draws = sample_counts([20.0], [12.0], [30.0], rng, draws=40_000)[:, 0]

    assert draws.dtype == np.int64 and draws.min() >= 0
    assert draws.mean() == pytest.approx(20.0, rel=0.03)
    q10, q90 = np.quantile(draws, [0.1, 0.9])
    assert 16 <= q90 - q10 <= 20  # target 18, normal-approximation match


def test_available_beds_stay_within_zero_and_open_beds_with_ordered_quantiles() -> None:
    rng = np.random.default_rng(1)

    out = simulate_unit(unit(arrivals_centre=[8.0] * DAYS, arrivals_q90=[14.0] * DAYS), rng)

    assert out.available.shape == (2_000, DAYS)
    assert out.available.min() >= 0 and out.available.max() <= 20
    assert out.available_raw.min() < 0  # more arrivals than beds: patients without a bed
    s = summarise(out.available)
    assert np.all((s.q10 <= s.q50) & (s.q50 <= s.q90))


def test_everyone_leaving_today_with_no_arrivals_frees_the_whole_unit() -> None:
    rng = np.random.default_rng(2)
    nobody = {"arrivals_centre": [0.0] * DAYS, "arrivals_q10": [0.0] * DAYS}

    out = simulate_unit(unit(discharge_cdfs=np.ones((18, DAYS)), **nobody), rng)

    assert np.all(out.available == 20)
    assert np.all(out.discharges[:, 0] == 18) and np.all(out.discharges[:, 1:] == 0)


def test_promised_admissions_are_a_floor_on_arrivals() -> None:
    rng = np.random.default_rng(3)
    nobody = {"arrivals_centre": [0.0] * DAYS, "arrivals_q10": [0.0] * DAYS}

    out = simulate_unit(
        unit(
            occupied=10,
            discharge_cdfs=np.zeros((10, DAYS)),
            new_stay_cdf=np.zeros(DAYS),
            promised_cum=[3, 3, 5, 5, 5, 5, 5, 5],
            **nobody,
        ),
        rng,
    )

    assert out.available[0].tolist() == [7, 7, 5, 5, 5, 5, 5, 5]
    assert out.arrivals[0].tolist() == [3, 0, 2, 0, 0, 0, 0, 0]


def test_arrivals_who_leave_the_same_day_do_not_take_a_bed_at_night() -> None:
    rng = np.random.default_rng(4)

    out = simulate_unit(
        unit(
            occupied=10,
            discharge_cdfs=np.zeros((10, DAYS)),
            new_stay_cdf=np.ones(DAYS),
            arrivals_centre=[5.0] * DAYS,
        ),
        rng,
    )

    assert np.all(out.available == 10)
    assert np.array_equal(out.discharges, out.arrivals)


def test_aggregation_sums_draws_within_each_scope() -> None:
    a = np.array([[1, 2], [3, 4]])
    b = np.array([[10, 20], [30, 40]])

    out = aggregate({1: a, 2: b, 3: a}, {1: "site:1", 2: "site:1", 3: "site:2"})

    assert out["site:1"].tolist() == [[11, 22], [33, 44]]
    assert out["site:2"].tolist() == a.tolist()


def test_a_common_shock_widens_the_aggregate_but_not_each_unit() -> None:
    def spread(common_variance: float) -> tuple[float, float]:
        rng = np.random.default_rng(5)
        common = gamma_factor(common_variance, (20_000, 1), rng)
        units = [
            sample_counts([10.0], [5.0], [15.0], rng, common, common_variance, 20_000)
            for _ in range(8)
        ]
        return float(np.std(units[0])), float(np.std(sum(units)))

    unit_alone, total_alone = spread(0.0)
    unit_shared, total_shared = spread(0.03)

    assert unit_shared == pytest.approx(unit_alone, rel=0.05)
    assert total_shared > 1.2 * total_alone


def test_common_shock_variance_is_recovered_from_relative_errors() -> None:
    rng = np.random.default_rng(6)
    shared = rng.gamma(1 / 0.04, 0.04, 4_000)
    errors = [rng.poisson(30 * shared) / 30 - 1 for _ in range(6)]

    assert common_shock_variance(errors) == pytest.approx(0.04, abs=0.006)


def test_tension_probabilities_follow_the_liscop_thresholds() -> None:
    # 20 installed beds: tension below 20 % (4 beds), critique at 0.
    assert TENSION_NORMAL_MIN == 0.2
    available = np.array([[0], [3], [4], [10]])

    p_tension, p_critique = tension_probabilities(available, [20])

    assert p_tension.tolist() == [0.5] and p_critique.tolist() == [0.25]


def test_weekday_retention_reproduces_a_weekend_profile() -> None:
    # Arrange: 60 % of weekend discharges done on Monday (Monday first).
    profile = [2.2, 1.0, 1.0, 1.0, 1.0, 0.4, 0.4]

    # Act
    keep = weekday_retention(profile)

    # Assert: even daily discharges, postponed as computed, give back the profile.
    carry, seen = 0.0, []
    for _ in range(3):
        for d in range(7):
            due = 1.0 + carry
            seen.append(due * keep[d])
            carry = due - seen[-1]
    assert seen[-7:] == pytest.approx(profile, abs=1e-6)


def test_postponed_discharges_move_to_the_next_day() -> None:
    rng = np.random.default_rng(8)
    nobody = {"arrivals_centre": [0.0] * DAYS, "arrivals_q10": [0.0] * DAYS}
    everyone_today = np.tile(np.ones(DAYS), (18, 1))

    out = simulate_unit(
        unit(discharge_cdfs=everyone_today, discharge_retention=[0.0, 1.0] + [1.0] * 6, **nobody),
        rng,
    )

    assert np.all(out.discharges[:, 0] == 0) and np.all(out.discharges[:, 1] == 18)
    assert np.all(out.available[:, 0] == 2) and np.all(out.available[:, 1] == 20)
