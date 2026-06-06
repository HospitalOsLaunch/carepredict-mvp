"""Moirai cold-start forecasting wrapper.

Moirai/uni2ts is treated as an optional local backend. The wrapper never downloads
weights by itself, which keeps CarePredict compatible with air-gapped deployments.
When uni2ts is not installed or no local checkpoint is configured, a deterministic
seasonal-naive fallback is used for CI, smoke tests and cold-start bootstrapping.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt
import pandas as pd
import structlog

LOGGER = structlog.get_logger(__name__)


@runtime_checkable
class TimeSeriesDataset(Protocol):
    """Minimal dataset protocol accepted by the Moirai fine-tuning wrapper."""

    def to_pandas(self) -> pd.DataFrame:
        """Return a dataframe containing at least timestamp, item_id and target columns."""
        ...


class MoiraiBackend(Protocol):
    """Backend protocol for a concrete uni2ts Moirai adapter."""

    def predict(self, history: pd.Series, horizon: int) -> npt.NDArray[np.float64]:
        """Predict the next ``horizon`` values."""
        ...

    def fine_tune(self, dataset: TimeSeriesDataset, epochs: int) -> dict[str, float]:
        """Fine-tune the model and return training metrics."""
        ...


@dataclass(frozen=True, slots=True)
class MoiraiConfig:
    """Configuration for :class:`MoiraiWrapper`."""

    model_name: str = "Salesforce/moirai-1.0-R-small"
    prediction_length: int = 12
    context_length: int = 168
    frequency: str = "h"
    local_checkpoint_path: Path | None = None
    allow_fallback: bool = True
    mlflow_experiment_name: str = "carepredict-moirai"

    def __post_init__(self) -> None:
        """Validate Moirai runtime configuration."""
        if self.prediction_length <= 0:
            raise ValueError("prediction_length must be strictly positive")
        if self.context_length <= 0:
            raise ValueError("context_length must be strictly positive")
        if self.local_checkpoint_path is not None and not self.local_checkpoint_path.exists():
            raise ValueError("local_checkpoint_path must exist when provided")


@dataclass(frozen=True, slots=True)
class ForecastResult:
    """Forecast values and metadata emitted by the wrapper."""

    values: npt.NDArray[np.float64]
    horizon: int
    backend_name: str
    model_version: str


@dataclass(frozen=True, slots=True)
class FineTuneResult:
    """Fine-tuning metrics and backend metadata."""

    backend_name: str
    epochs: int
    metrics: dict[str, float]
    model_version: str


class SeasonalNaiveBackend:
    """Small deterministic fallback used when uni2ts is unavailable locally."""

    name = "seasonal_naive_fallback"

    def __init__(self, season_length: int = 24) -> None:
        if season_length <= 0:
            raise ValueError("season_length must be strictly positive")
        self.season_length = season_length

    def predict(self, history: pd.Series, horizon: int) -> npt.NDArray[np.float64]:
        """Repeat the most recent daily seasonal pattern."""
        clean_history = history.dropna().astype(float)
        if clean_history.empty:
            raise ValueError("history must contain at least one non-null value")

        pattern_length = min(self.season_length, len(clean_history))
        pattern = clean_history.tail(pattern_length).to_numpy(dtype=float)
        repeats = int(np.ceil(horizon / len(pattern)))
        return np.tile(pattern, repeats)[:horizon].astype(float)

    def fine_tune(self, dataset: TimeSeriesDataset, epochs: int) -> dict[str, float]:
        """Return deterministic baseline metrics for compatibility with pipelines."""
        frame = dataset.to_pandas()
        if "target" not in frame.columns:
            raise ValueError("dataset must expose a target column")
        target = frame["target"].astype(float)
        baseline = target.shift(24).fillna(target.expanding().mean())
        mae = float((target - baseline).abs().mean())
        return {"baseline_mae": mae, "epochs": float(epochs)}


class Uni2TSMoiraiBackend:
    """Adapter boundary for local uni2ts Moirai usage.

    The concrete uni2ts API has varied between releases. This class intentionally
    validates availability and configuration, then fails with an actionable error
    until a local checkpoint-backed adapter is wired for the deployment target.
    """

    name = "uni2ts_moirai"

    def __init__(self, config: MoiraiConfig) -> None:
        self.config = config
        self._validate_uni2ts_available()

    def predict(self, history: pd.Series, horizon: int) -> npt.NDArray[np.float64]:
        """Predict with local uni2ts Moirai weights."""
        raise NotImplementedError(
            "uni2ts Moirai backend is available but no local checkpoint adapter is configured"
        )

    def fine_tune(self, dataset: TimeSeriesDataset, epochs: int) -> dict[str, float]:
        """Fine-tune local uni2ts Moirai weights."""
        raise NotImplementedError(
            "uni2ts Moirai fine-tuning requires deployment-specific local checkpoint wiring"
        )

    @staticmethod
    def _validate_uni2ts_available() -> None:
        try:
            __import__("uni2ts")
        except ImportError as exc:
            raise RuntimeError("uni2ts is not installed in this environment") from exc


class MoiraiWrapper:
    """Cold-start forecaster around Moirai with an air-gapped fallback."""

    def __init__(self, config: MoiraiConfig | None = None, backend: MoiraiBackend | None = None) -> None:
        self.config = config or MoiraiConfig()
        self._backend = backend or self._build_backend()

    @property
    def backend_name(self) -> str:
        """Return the active backend name."""
        return getattr(self._backend, "name", self._backend.__class__.__name__)

    def predict(self, history: pd.Series, horizon: int = 12) -> npt.NDArray[np.float64]:
        """Predict future care-load values from a historical hourly series."""
        self._validate_history(history)
        self._validate_horizon(horizon)
        forecast = self._backend.predict(history, horizon)
        forecast_array = np.asarray(forecast, dtype=float)
        if forecast_array.shape != (horizon,):
            raise ValueError("backend forecast must be a one-dimensional array matching horizon")

        LOGGER.info(
            "moirai_prediction_completed",
            backend=self.backend_name,
            horizon=horizon,
            history_points=len(history),
        )
        return forecast_array

    def predict_with_metadata(self, history: pd.Series, horizon: int = 12) -> ForecastResult:
        """Predict and return metadata for MLflow/API consumers."""
        values = self.predict(history=history, horizon=horizon)
        return ForecastResult(
            values=values,
            horizon=horizon,
            backend_name=self.backend_name,
            model_version=self.model_version,
        )

    def fine_tune(self, dataset: TimeSeriesDataset, epochs: int) -> FineTuneResult:
        """Fine-tune the active backend and log metrics when MLflow is installed."""
        if epochs <= 0:
            raise ValueError("epochs must be strictly positive")
        metrics = self._backend.fine_tune(dataset, epochs)
        result = FineTuneResult(
            backend_name=self.backend_name,
            epochs=epochs,
            metrics=metrics,
            model_version=self.model_version,
        )
        self._log_to_mlflow(result)
        return result

    @property
    def model_version(self) -> str:
        """Return a stable version label for cold-start baseline metadata."""
        return f"moirai-cold-start-{self.backend_name}"

    def _build_backend(self) -> MoiraiBackend:
        if self.config.local_checkpoint_path is not None:
            try:
                return Uni2TSMoiraiBackend(self.config)
            except RuntimeError:
                if not self.config.allow_fallback:
                    raise
                LOGGER.warning(
                    "moirai_backend_unavailable_using_fallback",
                    model_name=self.config.model_name,
                    checkpoint=str(self.config.local_checkpoint_path),
                )

        if not self.config.allow_fallback:
            raise RuntimeError("Moirai backend unavailable and fallback is disabled")
        return SeasonalNaiveBackend()

    @staticmethod
    def _validate_history(history: pd.Series) -> None:
        if history.empty:
            raise ValueError("history must not be empty")
        if not pd.api.types.is_numeric_dtype(history):
            raise ValueError("history must be numeric")
        if history.dropna().empty:
            raise ValueError("history must contain at least one non-null value")

    @staticmethod
    def _validate_horizon(horizon: int) -> None:
        if horizon <= 0:
            raise ValueError("horizon must be strictly positive")

    def _log_to_mlflow(self, result: FineTuneResult) -> None:
        try:
            import mlflow
        except ImportError:
            LOGGER.info("mlflow_not_installed_skipping_moirai_logging")
            return

        mlflow.set_experiment(self.config.mlflow_experiment_name)
        with mlflow.start_run(run_name="moirai_fine_tune"):
            mlflow.log_params(
                {
                    "backend_name": result.backend_name,
                    "epochs": result.epochs,
                    "model_name": self.config.model_name,
                    "prediction_length": self.config.prediction_length,
                    "context_length": self.config.context_length,
                    "frequency": self.config.frequency,
                }
            )
            mlflow.log_metrics(result.metrics)
            mlflow.set_tags(
                {
                    "model_version": result.model_version,
                    "carepredict_component": "moirai_wrapper",
                    "config": str(asdict(self.config)),
                }
            )
