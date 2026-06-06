"""Tests for conformal prediction intervals."""

from __future__ import annotations

import pytest

from services.ml.uq.conformal import ConformalConfig, ConformalForecaster


def test_conformal_calibrates_and_predicts_interval() -> None:
    forecaster = ConformalForecaster(ConformalConfig(coverage=0.90, allow_mapie=False))
    quantile = forecaster.calibrate(
        y_true=[10.0, 11.0, 12.0, 13.0, 14.0],
        y_pred=[9.5, 11.2, 11.0, 13.4, 13.0],
    )

    interval = forecaster.predict_interval(12.0)

    assert quantile >= 0
    assert interval.lower <= 12.0 <= interval.upper
    assert interval.coverage == 0.90


def test_conformal_empirical_coverage() -> None:
    forecaster = ConformalForecaster.from_residual_quantile(
        residual_quantile=1.0,
        config=ConformalConfig(coverage=0.90, allow_mapie=False),
    )

    coverage = forecaster.empirical_coverage(
        y_true=[10.0, 12.0, 14.0, 20.0],
        y_pred=[10.5, 11.5, 15.2, 18.5],
    )

    assert coverage == 0.5


def test_conformal_requires_calibration() -> None:
    forecaster = ConformalForecaster()

    with pytest.raises(RuntimeError, match="calibrated"):
        forecaster.predict_interval(10.0)


def test_conformal_rejects_mismatched_arrays() -> None:
    forecaster = ConformalForecaster()

    with pytest.raises(ValueError, match="matching shapes"):
        forecaster.calibrate(y_true=[1.0, 2.0], y_pred=[1.0])
