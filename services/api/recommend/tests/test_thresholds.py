"""Unit tests for forecast-space threshold providers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pytest

from services.api.recommend.thresholds import ForecastP75ThresholdProvider


@dataclass(frozen=True, slots=True)
class FakeWindow:
    """Feature-window fixture."""

    history: list[list[float]]


class FakeForecastService:
    """Forecast service fixture returning one configured maximum per call."""

    artifacts = object()
    history_length = 120

    def __init__(self, maxima: list[float]) -> None:
        self.maxima = maxima
        self.calls = 0

    def forecast(
        self,
        *,
        history: list[list[float]],
        origin_timestamp: datetime,
        horizon: int,
    ) -> list[dict[str, float | int]]:
        maximum = self.maxima[self.calls]
        self.calls += 1
        return [
            {
                "step_index": 1,
                "predicted_siips": maximum - 10.0,
                "lower_90": maximum - 20.0,
                "upper_90": maximum,
            },
            {
                "step_index": 2,
                "predicted_siips": maximum,
                "lower_90": maximum - 5.0,
                "upper_90": maximum + 5.0,
            },
        ]


class FakeFetcher:
    """Feature-window fetcher fixture."""

    def __init__(self, *, fail_after: int | None = None) -> None:
        self.calls = 0
        self.fail_after = fail_after

    def fetch(
        self,
        *,
        hospital_id: str,
        service_id: str,
        origin_timestamp: datetime,
        length: int,
        artifacts: object,
    ) -> FakeWindow:
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise ValueError("missing feature window")
        return FakeWindow(history=[[0.0] * 7 for _ in range(length)])


def test_threshold_for_computes_forecast_max_percentile() -> None:
    service = FakeForecastService(maxima=[100.0, 200.0, 300.0, 400.0])
    fetcher = FakeFetcher()
    provider = ForecastP75ThresholdProvider(
        forecast_service=service,
        feature_fetcher=fetcher,
        n_samples=4,
        percentile=75.0,
        min_valid=4,
    )

    threshold = provider.threshold_for(hospital_id="hosp-001", service_id="urg-001")

    assert threshold == pytest.approx(325.0)
    assert service.calls == 4
    assert fetcher.calls == 4


def test_threshold_for_uses_instance_cache() -> None:
    service = FakeForecastService(maxima=[100.0, 200.0, 300.0, 400.0])
    fetcher = FakeFetcher()
    provider = ForecastP75ThresholdProvider(
        forecast_service=service,
        feature_fetcher=fetcher,
        n_samples=4,
        percentile=75.0,
        min_valid=4,
    )

    first = provider.threshold_for(hospital_id="hosp-001", service_id="rea-001")
    second = provider.threshold_for(hospital_id="hosp-001", service_id="rea-001")

    assert first == second == pytest.approx(325.0)
    assert service.calls == 4
    assert fetcher.calls == 4


def test_threshold_for_requires_minimum_valid_samples() -> None:
    service = FakeForecastService(maxima=[100.0, 200.0])
    fetcher = FakeFetcher(fail_after=2)
    provider = ForecastP75ThresholdProvider(
        forecast_service=service,
        feature_fetcher=fetcher,
        n_samples=4,
        percentile=75.0,
        min_valid=3,
    )

    with pytest.raises(RuntimeError, match="at least 3 are required"):
        provider.threshold_for(hospital_id="hosp-001", service_id="ssr-001")
