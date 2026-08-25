"""Moirai cold-start forecasting wrapper.

Moirai/uni2ts is treated as an optional local backend. The wrapper downloads
weights once from HuggingFace (Salesforce/moirai-1.0-R-small by default). When
uni2ts is not installed, a deterministic seasonal-naive fallback is used.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol, cast, runtime_checkable

import numpy as np
import numpy.typing as npt
import pandas as pd
import structlog

LOGGER = structlog.get_logger(__name__)


@runtime_checkable
class TimeSeriesDataset(Protocol):
    """Minimal dataset protocol accepted by the Moirai fine-tuning wrapper."""

    def to_pandas(self) -> pd.DataFrame: ...


class MoiraiBackend(Protocol):
    """Backend protocol for a concrete uni2ts Moirai adapter."""

    def predict(self, history: pd.Series, horizon: int) -> npt.NDArray[np.float64]: ...

    def fine_tune(self, dataset: TimeSeriesDataset, epochs: int) -> dict[str, float]: ...


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
    num_samples: int = 100
    patch_size: str | int = "auto"

    def __post_init__(self) -> None:
        if self.prediction_length <= 0:
            raise ValueError("prediction_length must be strictly positive")
        if self.context_length <= 0:
            raise ValueError("context_length must be strictly positive")
        if self.local_checkpoint_path is not None and not self.local_checkpoint_path.exists():
            raise ValueError("local_checkpoint_path must exist when provided")


@dataclass(frozen=True, slots=True)
class ForecastResult:
    values: npt.NDArray[np.float64]
    horizon: int
    backend_name: str
    model_version: str


@dataclass(frozen=True, slots=True)
class FineTuneResult:
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
        clean_history = history.dropna().astype(float)
        if clean_history.empty:
            raise ValueError("history must contain at least one non-null value")
        pattern_length = min(self.season_length, len(clean_history))
        pattern = clean_history.tail(pattern_length).to_numpy(dtype=float)
        repeats = int(np.ceil(horizon / len(pattern)))
        return np.tile(pattern, repeats)[:horizon].astype(float)

    def fine_tune(self, dataset: TimeSeriesDataset, epochs: int) -> dict[str, float]:
        frame = dataset.to_pandas()
        if "target" not in frame.columns:
            raise ValueError("dataset must expose a target column")
        target = frame["target"].astype(float)
        baseline = target.shift(24).fillna(target.expanding().mean())
        mae = float((target - baseline).abs().mean())
        return {"baseline_mae": mae, "epochs": float(epochs)}


class Uni2TSMoiraiBackend:
    """Real adapter around uni2ts MoiraiForecast for zero-shot prediction."""

    name = "uni2ts_moirai"

    def __init__(self, config: MoiraiConfig) -> None:
        self.config = config
        self._validate_uni2ts_available()
        self._forecast: Any = None  # MoiraiForecast instance
        self._build_forecaster()

    def predict(self, history: pd.Series, horizon: int) -> npt.NDArray[np.float64]:
        """Predict horizon values using zero-shot Moirai weights."""
        import torch

        if self._forecast is None:
            self._build_forecaster(horizon_override=horizon)

        clean = history.dropna().astype(float)
        if clean.empty:
            raise ValueError("history must contain at least one non-null value")

        context_length = min(self.config.context_length, len(clean))
        context = clean.tail(context_length).to_numpy(dtype=np.float32)

        past_target = torch.from_numpy(context).reshape(1, -1, 1)
        past_observed_target = torch.ones_like(past_target, dtype=torch.bool)
        past_is_pad = torch.zeros(past_target.shape[:-1], dtype=torch.bool)

        self._forecast.eval()
        with torch.no_grad():
            samples = self._forecast(
                past_target=past_target,
                past_observed_target=past_observed_target,
                past_is_pad=past_is_pad,
            )

        samples_np = samples.detach().cpu().numpy()
        # Shape: [num_samples, batch=1, horizon, target_dim=1]
        median = np.median(samples_np, axis=0).squeeze()
        if median.ndim == 0:
            median = np.array([float(median)])
        if median.shape[0] < horizon:
            pad = np.full(horizon - median.shape[0], float(median[-1]), dtype=float)
            median = np.concatenate([median, pad])
        return cast(npt.NDArray[np.float64], median[:horizon].astype(float))

    def fine_tune(self, dataset: TimeSeriesDataset, epochs: int) -> dict[str, float]:
        """Evaluate zero-shot Moirai on the dataset.

        Proper LoRA fine-tuning of Moirai is deployment-specific and requires
        a curated medical corpus. Here we evaluate the zero-shot performance
        across the dataset and return MAE/MAPE as cold-start baseline metrics.
        """
        frame = dataset.to_pandas()
        if "target" not in frame.columns:
            raise ValueError("dataset must expose a target column")

        target = frame["target"].astype(float).dropna()
        if target.empty:
            return {"baseline_mae": 0.0, "epochs": float(epochs)}

        horizon = self.config.prediction_length
        context_length = self.config.context_length
        if len(target) <= context_length + horizon:
            return {"baseline_mae": float(target.std() or 1.0), "epochs": float(epochs)}

        # Rolling evaluation across at most 30 windows
        max_windows = 30
        step = max(1, (len(target) - context_length - horizon) // max_windows)
        errors: list[float] = []
        for start in range(0, len(target) - context_length - horizon, step):
            history = target.iloc[start : start + context_length]
            truth = target.iloc[start + context_length : start + context_length + horizon].to_numpy(
                dtype=float
            )
            try:
                forecast = self.predict(history, horizon=horizon)
                errors.append(float(np.mean(np.abs(forecast - truth))))
            except Exception as exc:  # noqa: BLE001
                LOGGER.debug("moirai_zero_shot_window_failed", error=str(exc))
                continue
            if len(errors) >= max_windows:
                break

        mae = float(np.mean(errors)) if errors else float(target.std() or 1.0)
        LOGGER.info(
            "moirai_zero_shot_evaluation_completed",
            backend=self.name,
            windows=len(errors),
            mae=mae,
        )
        return {"baseline_mae": mae, "epochs": float(epochs), "windows": float(len(errors))}

    def _build_forecaster(self, horizon_override: int | None = None) -> None:
        from uni2ts.model.moirai import (  # type: ignore[import-untyped]
            MoiraiForecast,
            MoiraiModule,
        )

        source = (
            str(self.config.local_checkpoint_path)
            if self.config.local_checkpoint_path is not None
            else self.config.model_name
        )
        module = MoiraiModule.from_pretrained(source)
        self._forecast = MoiraiForecast(
            module=module,
            prediction_length=horizon_override or self.config.prediction_length,
            context_length=self.config.context_length,
            patch_size=self.config.patch_size,
            num_samples=self.config.num_samples,
            target_dim=1,
            feat_dynamic_real_dim=0,
            past_feat_dynamic_real_dim=0,
        )

    @staticmethod
    def _validate_uni2ts_available() -> None:
        try:
            __import__("uni2ts")
        except ImportError as exc:
            raise RuntimeError("uni2ts is not installed in this environment") from exc


class MoiraiWrapper:
    """Cold-start forecaster around Moirai with an air-gapped fallback."""

    def __init__(
        self,
        config: MoiraiConfig | None = None,
        backend: MoiraiBackend | None = None,
    ) -> None:
        self.config = config or MoiraiConfig()
        self._backend = backend or self._build_backend()

    @property
    def backend_name(self) -> str:
        return getattr(self._backend, "name", self._backend.__class__.__name__)

    def predict(self, history: pd.Series, horizon: int = 12) -> npt.NDArray[np.float64]:
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
        values = self.predict(history=history, horizon=horizon)
        return ForecastResult(
            values=values,
            horizon=horizon,
            backend_name=self.backend_name,
            model_version=self.model_version,
        )

    def fine_tune(self, dataset: TimeSeriesDataset, epochs: int) -> FineTuneResult:
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
        return f"moirai-cold-start-{self.backend_name}"

    def _build_backend(self) -> MoiraiBackend:
        try:
            return Uni2TSMoiraiBackend(self.config)
        except RuntimeError as exc:
            if not self.config.allow_fallback:
                raise
            LOGGER.warning(
                "moirai_backend_unavailable_using_fallback",
                model_name=self.config.model_name,
                error=str(exc),
            )
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


# Backwards-compatible alias for older diagnostic scripts.
MoiraiForecaster = MoiraiWrapper
