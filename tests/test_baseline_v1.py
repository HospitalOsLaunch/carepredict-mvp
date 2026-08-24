"""Unit tests for frozen v1 baseline evaluation helpers."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np

from hospitalos.eval.baseline_v1 import (
    CareLoadPoint,
    ForecastRecord,
    bootstrap_mae_ci,
    collect_forecast_records,
    history_until,
    metric_block,
    seasonal_metric_block,
    zero_actions,
)


class FakeService:
    """Tiny deterministic simulator for open-loop helper tests."""

    model_version = "fake-v1"

    def __init__(self) -> None:
        self.histories: list[list[float]] = []

    def simulate(
        self, history_siips: list[float], action_sequence: list[list[float]]
    ) -> list[dict[str, float | int | bool]]:
        self.histories.append(list(history_siips))
        baseline = float(history_siips[-1])
        return [
            {
                "step_index": index,
                "predicted_siips": baseline + float(index + 1),
                "lower_bound": baseline + float(index),
                "upper_bound": baseline + float(index + 2),
                "reward": 0.0,
                "is_critical": False,
            }
            for index, _action in enumerate(action_sequence)
        ]


def test_metric_block_and_coverage() -> None:
    """Metric helper computes MAE, RMSE, coverage and interval width."""
    records = [
        ForecastRecord(
            origin=datetime(2025, 7, 1, tzinfo=UTC),
            horizon=24,
            y_true=10.0,
            y_pred=8.0,
            lower=7.0,
            upper=11.0,
            seasonal_naive=9.0,
        ),
        ForecastRecord(
            origin=datetime(2025, 7, 2, tzinfo=UTC),
            horizon=24,
            y_true=20.0,
            y_pred=23.0,
            lower=21.0,
            upper=25.0,
            seasonal_naive=19.0,
        ),
    ]
    metrics = metric_block(records, seed=0)
    assert metrics["n_samples"] == 2
    assert metrics["mae"] == 2.5
    assert math.isclose(metrics["rmse"], math.sqrt(6.5))
    assert metrics["mapie_coverage_90"] == 0.5
    assert metrics["mean_interval_width"] == 4.0
    assert len(metrics["mae_ci_95"]) == 2


def test_seasonal_naive_metrics() -> None:
    """Seasonal floor is evaluated on the same origin-target pairs."""
    records = [
        ForecastRecord(
            origin=datetime(2025, 7, 1, tzinfo=UTC),
            horizon=48,
            y_true=100.0,
            y_pred=90.0,
            lower=80.0,
            upper=120.0,
            seasonal_naive=95.0,
        )
    ]
    metrics = seasonal_metric_block(records, seed=0)
    assert metrics["n_samples"] == 1
    assert metrics["mae"] == 5.0
    assert metrics["rmse"] == 5.0


def test_bootstrap_ci_is_seeded() -> None:
    """Bootstrap CI is deterministic for a fixed seed."""
    errors = np.asarray([1.0, 2.0, 3.0, 4.0], dtype=np.float64)
    assert bootstrap_mae_ci(errors, seed=123) == bootstrap_mae_ci(errors, seed=123)


def test_history_until_enforces_open_loop_slice() -> None:
    """History extraction ignores rows after the origin."""
    origin = datetime(2025, 7, 2, tzinfo=UTC)
    points = [
        CareLoadPoint("urg-001", origin - timedelta(hours=1), 10.0),
        CareLoadPoint("urg-001", origin, 20.0),
        CareLoadPoint("urg-001", origin + timedelta(hours=1), 999.0),
    ]
    assert history_until(points, origin) == [10.0, 20.0]


def test_collect_forecast_records_open_loop_same_with_future_rows() -> None:
    """Predictions are identical whether future rows are present in the input frame."""
    start = datetime(2025, 6, 24, tzinfo=UTC)
    points = [
        CareLoadPoint("urg-001", start + timedelta(hours=hour), float(100 + hour))
        for hour in range(240)
    ]
    origin = datetime(2025, 7, 1, tzinfo=UTC)
    service_with_future = FakeService()
    service_trimmed = FakeService()

    with_future = collect_forecast_records(
        service=service_with_future,
        points=points,
        train_end=origin,
        horizon=24,
        stride_hours=24,
    )
    trimmed = collect_forecast_records(
        service=service_trimmed,
        points=[point for point in points if point.measured_at <= origin + timedelta(hours=24)],
        train_end=origin,
        horizon=24,
        stride_hours=24,
    )
    assert with_future[0].y_pred == trimmed[0].y_pred
    assert service_with_future.histories[0] == service_trimmed.histories[0]


def test_zero_actions_shape() -> None:
    """Zero future actions match the v1 action contract."""
    assert zero_actions(horizon=3, action_dim=5) == [
        [0.0, 0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0, 0.0],
    ]
