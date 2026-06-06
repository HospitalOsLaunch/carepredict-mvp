"""Temporal Fusion Transformer wrapper for CarePredict.

The production path is designed around ``pytorch-forecasting``. To keep the MVP
testable in air-gapped CI and on machines without the optional dependency, the
wrapper also provides a deterministic interpretable fallback that consumes the
same future intervention covariates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import numpy as np
import numpy.typing as npt
import pandas as pd
import structlog

LOGGER = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class FutureIntervention:
    """Known future intervention used as a TFT covariate."""

    intervention_type: str
    scheduled_at: datetime
    count: int

    def __post_init__(self) -> None:
        """Validate intervention payload."""
        if self.count < 0:
            raise ValueError("intervention count must be non-negative")
        if not self.intervention_type:
            raise ValueError("intervention_type must not be empty")


@dataclass(frozen=True, slots=True)
class TFTConfig:
    """Configuration for the TFT forecasting wrapper."""

    horizon: int = 12
    step_hours: int = 1
    target_column: str = "siips_score"
    service_column: str = "service_id"
    time_column: str = "timestamp"
    static_categoricals: tuple[str, ...] = ("service_id", "hospital_profile")
    known_future_reals: tuple[str, ...] = (
        "planned_staff_redeployments",
        "scheduled_discharges",
        "scheduled_surgeries",
        "expected_transfers_in",
        "expected_transfers_out",
        "scheduled_admissions",
        "planned_procedures",
    )
    max_encoder_length: int = 24
    allow_fallback: bool = True
    model_version: str = "tft-moirai-ft-v1.0"

    def __post_init__(self) -> None:
        """Validate model config."""
        if self.horizon <= 0:
            raise ValueError("horizon must be strictly positive")
        if self.step_hours <= 0:
            raise ValueError("step_hours must be strictly positive")
        if self.max_encoder_length <= 0:
            raise ValueError("max_encoder_length must be strictly positive")


@dataclass(frozen=True, slots=True)
class TFTForecast:
    """Forecast and attention-style feature attribution summary."""

    value: float
    horizon_values: npt.NDArray[np.float64]
    top_features: list[str]
    model_version: str


class TFTBackend(Protocol):
    """Backend protocol for TFT implementations."""

    def predict(
        self,
        history: pd.DataFrame,
        future_covariates: pd.DataFrame,
        config: TFTConfig,
    ) -> TFTForecast:
        """Predict a 12h care-load forecast."""
        ...

    def fit(self, dataset: pd.DataFrame, config: TFTConfig) -> dict[str, float]:
        """Fit the backend and return training metrics."""
        ...


class PytorchForecastingTFTBackend:
    """Optional adapter boundary for ``pytorch-forecasting``."""

    name = "pytorch_forecasting_tft"

    def __init__(self) -> None:
        self._validate_dependency()

    def predict(
        self,
        history: pd.DataFrame,
        future_covariates: pd.DataFrame,
        config: TFTConfig,
    ) -> TFTForecast:
        """Predict with a trained pytorch-forecasting TFT model."""
        raise NotImplementedError(
            "A trained TemporalFusionTransformer checkpoint is required before prediction"
        )

    def fit(self, dataset: pd.DataFrame, config: TFTConfig) -> dict[str, float]:
        """Fit a pytorch-forecasting TFT model."""
        raise NotImplementedError(
            "TFT training is wired in services.ml.training.train_tft for deployment runs"
        )

    @staticmethod
    def _validate_dependency() -> None:
        try:
            __import__("pytorch_forecasting")
        except ImportError as exc:
            raise RuntimeError("pytorch-forecasting is not installed") from exc


class InterpretableTFTFallback:
    """Small deterministic forecaster that mirrors TFT covariate semantics."""

    name = "interpretable_tft_fallback"

    _FEATURE_IMPACTS: dict[str, float] = {
        "scheduled_discharges": -1.8,
        "scheduled_surgeries": 1.2,
        "expected_transfers_in": 1.4,
        "expected_transfers_out": -1.1,
        "scheduled_admissions": 1.7,
        "planned_procedures": 0.8,
        "planned_staff_redeployments": -0.6,
    }

    def predict(
        self,
        history: pd.DataFrame,
        future_covariates: pd.DataFrame,
        config: TFTConfig,
    ) -> TFTForecast:
        """Produce a transparent baseline forecast using trend and future events."""
        target = history[config.target_column].astype(float).dropna()
        if target.empty:
            raise ValueError("history target column must contain at least one non-null value")

        current = float(target.iloc[-1])
        trend = self._recent_hourly_trend(target)
        horizon_values: list[float] = []
        feature_scores = {feature: 0.0 for feature in config.known_future_reals}

        for step in range(1, config.horizon + 1):
            row = future_covariates.iloc[min(step - 1, len(future_covariates) - 1)]
            intervention_delta = 0.0
            for feature, impact in self._FEATURE_IMPACTS.items():
                if feature in row:
                    feature_value = float(row[feature])
                    intervention_delta += impact * feature_value
                    feature_scores[feature] += abs(impact * feature_value)
            seasonal_adjustment = 0.4 * np.sin((step / 24.0) * 2.0 * np.pi)
            horizon_values.append(current + trend * step + intervention_delta + seasonal_adjustment)

        top_features = [
            feature
            for feature, _score in sorted(
                feature_scores.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:3]
        ]
        if not any(feature_scores.values()):
            top_features = ["recent_siips_trend", "hour_of_day", "service_baseline"]

        forecast_array = np.asarray(horizon_values, dtype=float)
        return TFTForecast(
            value=float(forecast_array[-1]),
            horizon_values=forecast_array,
            top_features=top_features,
            model_version=config.model_version,
        )

    def fit(self, dataset: pd.DataFrame, config: TFTConfig) -> dict[str, float]:
        """Return deterministic baseline metrics for small integration tests."""
        target = dataset[config.target_column].astype(float)
        shifted = target.shift(config.horizon).fillna(target.expanding().mean())
        mae = float((target - shifted).abs().mean())
        mape = float(((target - shifted).abs() / target.clip(lower=1.0)).mean())
        return {"train_mae": mae, "train_mape": mape}

    @staticmethod
    def _recent_hourly_trend(target: pd.Series) -> float:
        if len(target) < 2:
            return 0.0
        window = target.tail(min(6, len(target)))
        return float((window.iloc[-1] - window.iloc[0]) / max(len(window) - 1, 1))


class CarePredictTFT:
    """TFT facade used by training, API and backtesting."""

    def __init__(self, config: TFTConfig | None = None, backend: TFTBackend | None = None) -> None:
        self.config = config or TFTConfig()
        self._backend = backend or self._build_backend()

    @property
    def backend_name(self) -> str:
        """Return the active backend name."""
        return getattr(self._backend, "name", self._backend.__class__.__name__)

    def predict(
        self,
        history: pd.DataFrame,
        future_covariates: pd.DataFrame | None = None,
        interventions: list[FutureIntervention] | None = None,
    ) -> TFTForecast:
        """Predict care load at J+12h using history and known future interventions."""
        self._validate_history(history)
        covariates = future_covariates
        if covariates is None:
            covariates = build_future_covariates(
                timestamp=self._latest_timestamp(history),
                interventions=interventions or [],
                config=self.config,
            )
        self._validate_future_covariates(covariates)
        forecast = self._backend.predict(history, covariates, self.config)
        LOGGER.info(
            "tft_prediction_completed",
            backend=self.backend_name,
            value=forecast.value,
            model_version=forecast.model_version,
        )
        return forecast

    def fit(self, dataset: pd.DataFrame) -> dict[str, float]:
        """Fit the active backend."""
        self._validate_history(dataset)
        return self._backend.fit(dataset, self.config)

    def _build_backend(self) -> TFTBackend:
        try:
            return PytorchForecastingTFTBackend()
        except RuntimeError:
            if not self.config.allow_fallback:
                raise
            LOGGER.warning("tft_backend_unavailable_using_fallback")
            return InterpretableTFTFallback()

    def _validate_history(self, history: pd.DataFrame) -> None:
        missing = {
            self.config.target_column,
            self.config.time_column,
            self.config.service_column,
        }.difference(history.columns)
        if missing:
            raise ValueError(f"history missing required columns: {sorted(missing)}")
        if history.empty:
            raise ValueError("history must not be empty")

    def _validate_future_covariates(self, future_covariates: pd.DataFrame) -> None:
        missing = set(self.config.known_future_reals).difference(future_covariates.columns)
        if missing:
            raise ValueError(f"future_covariates missing required columns: {sorted(missing)}")
        if len(future_covariates) < self.config.horizon:
            raise ValueError("future_covariates must contain at least horizon rows")

    def _latest_timestamp(self, history: pd.DataFrame) -> pd.Timestamp:
        return pd.to_datetime(history[self.config.time_column]).max()


def build_future_covariates(
    *,
    timestamp: pd.Timestamp,
    interventions: list[FutureIntervention],
    config: TFTConfig,
) -> pd.DataFrame:
    """Build hourly known-future covariates from planned interventions."""
    rows: list[dict[str, object]] = []
    base_timestamp = pd.Timestamp(timestamp)
    for step in range(1, config.horizon + 1):
        bucket_start = base_timestamp + pd.Timedelta(hours=step * config.step_hours)
        row: dict[str, object] = {
            "timestamp": bucket_start,
            **{feature: 0 for feature in config.known_future_reals},
        }
        for intervention in interventions:
            scheduled_at = pd.Timestamp(intervention.scheduled_at)
            if scheduled_at.floor("h") == bucket_start.floor("h"):
                feature_name = _intervention_to_feature(intervention.intervention_type)
                if feature_name in row:
                    row[feature_name] = int(row[feature_name]) + intervention.count
        rows.append(row)
    return pd.DataFrame(rows)


def _intervention_to_feature(intervention_type: str) -> str:
    mapping = {
        "staff_redeployment": "planned_staff_redeployments",
        "discharge": "scheduled_discharges",
        "surgery": "scheduled_surgeries",
        "transfer_in": "expected_transfers_in",
        "transfer_out": "expected_transfers_out",
        "admission": "scheduled_admissions",
        "procedure": "planned_procedures",
    }
    return mapping.get(intervention_type, intervention_type)
