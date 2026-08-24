"""Forecast-space risk thresholds for recommendation calibration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

import numpy as np
import structlog

from services.api.dependencies.feature_window_fetcher import TimescaleFeatureWindowFetcher
from services.ml.forecasting.v2_service import V2ForecastService

LOGGER = structlog.get_logger(__name__)
DEFAULT_RISK_THRESHOLD = 1600.0


class ServiceThresholdProvider(Protocol):
    """Provider for service-specific SIIPS risk thresholds."""

    def threshold_for(self, *, hospital_id: str, service_id: str) -> float:
        """Return the SIIPS risk threshold for one service."""


class ForecastServiceLike(Protocol):
    """Subset of ``V2ForecastService`` needed for threshold calibration."""

    artifacts: object
    history_length: int

    def forecast(
        self,
        *,
        history: list[list[float]],
        origin_timestamp: datetime,
        horizon: int,
    ) -> list[dict[str, float | int]]:
        """Return raw forecast dictionaries."""


class FeatureWindowFetcherLike(Protocol):
    """Subset of ``TimescaleFeatureWindowFetcher`` needed for calibration."""

    def fetch(
        self,
        *,
        hospital_id: str,
        service_id: str,
        origin_timestamp: datetime,
        length: int,
        artifacts: object,
    ) -> object:
        """Return an object with a ``history`` attribute."""


class ForecastP75ThresholdProvider:
    """Calibrate risk thresholds in the smoothed forecast space.

    The provider samples deterministic historical origins for a service,
    forecasts each origin, collects the per-origin maximum predicted SIIPS
    value, and returns the configured percentile of that forecast-max
    distribution. The calibration is lazy and cached per hospital/service.
    """

    def __init__(
        self,
        *,
        forecast_service: ForecastServiceLike | None = None,
        feature_fetcher: FeatureWindowFetcherLike | None = None,
        n_samples: int = 40,
        percentile: float = 75.0,
        sample_span_days: int = 600,
        sample_start: str = "2024-03-01",
        min_valid: int = 20,
    ) -> None:
        self.forecast_service = forecast_service or V2ForecastService.from_artifacts()
        self.feature_fetcher = feature_fetcher or TimescaleFeatureWindowFetcher()
        self.n_samples = n_samples
        self.percentile = percentile
        self.sample_span_days = sample_span_days
        self.sample_start = sample_start
        self.min_valid = min_valid
        self._cache: dict[tuple[str, str], float] = {}

    def threshold_for(self, *, hospital_id: str, service_id: str) -> float:
        """Return cached forecast-space P75 threshold for one service."""
        cache_key = (hospital_id, service_id)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        forecast_maxima: list[float] = []
        for origin in self._sample_origins():
            try:
                window = self.feature_fetcher.fetch(
                    hospital_id=hospital_id,
                    service_id=service_id,
                    origin_timestamp=origin,
                    length=self.forecast_service.history_length,
                    artifacts=self.forecast_service.artifacts,
                )
                raw_forecast = self.forecast_service.forecast(
                    history=window.history,
                    origin_timestamp=origin,
                    horizon=48,
                )
            except Exception as exc:
                LOGGER.warning(
                    "forecast_threshold_sample_skipped",
                    hospital_id=hospital_id,
                    service_id=service_id,
                    origin=origin.isoformat(),
                    error=str(exc),
                )
                continue

            if raw_forecast:
                forecast_maxima.append(max(float(item["predicted_siips"]) for item in raw_forecast))

        if len(forecast_maxima) < self.min_valid:
            raise RuntimeError(
                "forecast-space threshold calibration collected "
                f"{len(forecast_maxima)} valid samples for {hospital_id}/{service_id}; "
                f"at least {self.min_valid} are required"
            )

        threshold = float(np.percentile(forecast_maxima, self.percentile))
        self._cache[cache_key] = threshold
        return threshold

    def _sample_origins(self) -> list[datetime]:
        """Return deterministic origins evenly spaced across the sample span."""
        start = datetime.fromisoformat(self.sample_start).replace(tzinfo=UTC)
        if self.n_samples <= 1:
            return [start]
        span_hours = self.sample_span_days * 24
        offsets = np.rint(np.linspace(0, span_hours, num=self.n_samples)).astype(int)
        return [start + timedelta(hours=int(offset)) for offset in offsets]
