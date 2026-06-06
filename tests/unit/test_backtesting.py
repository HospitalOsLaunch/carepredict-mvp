"""Tests for backtesting metrics."""

from __future__ import annotations

import pytest

from services.ml.training.backtesting import (
    BacktestMetrics,
    assert_metric_targets,
    calculate_metrics,
)


def test_calculate_metrics_returns_expected_values() -> None:
    metrics = calculate_metrics(
        y_true=[10.0, 20.0],
        y_pred=[9.0, 22.0],
        lower=[8.0, 19.0],
        upper=[12.0, 24.0],
    )

    assert metrics.mae == 1.5
    assert metrics.coverage == 1.0


def test_assert_metric_targets_raises_clear_error() -> None:
    metrics = BacktestMetrics(mae=1.2, mape=0.2, crps=0.1, coverage=0.75, ece=0.15)

    with pytest.raises(RuntimeError, match="Backtesting metric targets failed"):
        assert_metric_targets(metrics)
