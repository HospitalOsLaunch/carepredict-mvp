"""Model selection by rolling-origin cross-validation, with the seasonal naive fallback."""

from __future__ import annotations

from datetime import date

import numpy as np

from services.forecast_engine.models import HORIZON, REFERENCE, forecast_series

LAST_DAY = date(2026, 6, 30)


def test_exact_weekly_pattern_keeps_the_seasonal_naive_reference() -> None:
    # Arrange: the same week repeated, which the reference forecasts without error.
    week = np.array([9, 7, 7, 6, 7, 3, 4], dtype=float)
    series = {"unit": np.tile(week, 30)}

    # Act
    fc = forecast_series(series, LAST_DAY)["unit"]

    # Assert
    assert fc.model == REFERENCE
    assert fc.fallback is True
    assert fc.cv_mae[REFERENCE] == 0.0
    assert len(fc.days) == HORIZON and fc.days[0] == date(2026, 7, 1)


def test_noisy_counts_select_a_smoothing_model_with_ordered_bounds() -> None:
    rng = np.random.default_rng(7)
    weekday = np.array([1.2, 1.0, 1.0, 1.0, 1.0, 0.8, 0.8])
    series = {"unit": rng.poisson(20 * np.tile(weekday, 30)).astype(float)}

    fc = forecast_series(series, LAST_DAY)["unit"]

    assert fc.model != REFERENCE and not fc.fallback
    assert fc.cv_mae[fc.model] < fc.cv_mae[REFERENCE]
    assert np.all(fc.point >= 0)
    assert np.all((fc.q10 >= 0) & (fc.q10 <= fc.q50) & (fc.q50 <= fc.q90))
    assert np.all(fc.q90 - fc.q10 > 0)
    assert set(fc.residuals) == set(range(1, HORIZON + 1))


def test_short_series_fall_back_without_cross_validation() -> None:
    series = {"new": np.array([1, 2, 3, 4, 5, 6, 7, 8], dtype=float)}

    fc = forecast_series(series, LAST_DAY)["new"]

    assert fc.model == REFERENCE and fc.fallback and fc.cv_mae == {}
    assert fc.point.tolist() == [2, 3, 4, 5, 6, 7, 8, 2]


def test_a_series_of_zeros_forecasts_zeros() -> None:
    fc = forecast_series({"empty": np.zeros(200)}, LAST_DAY)["empty"]

    assert np.all(fc.point == 0) and np.all(fc.q90 == 0)
