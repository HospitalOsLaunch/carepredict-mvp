"""Temporal Fusion Transformer wrapper for CarePredict.

The production path is designed around ``pytorch-forecasting``. To keep the MVP
testable in air-gapped CI and on machines without the optional dependency, the
wrapper also provides a deterministic interpretable fallback that consumes the
same future intervention covariates.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, cast

import numpy as np
import numpy.typing as npt
import pandas as pd
import structlog
import torch

LOGGER = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class FutureIntervention:
    """Known future intervention used as a TFT covariate."""

    intervention_type: str
    scheduled_at: datetime
    count: int

    def __post_init__(self) -> None:
        if self.count < 0:
            raise ValueError("intervention count must be non-negative")
        if not self.intervention_type:
            raise ValueError("intervention_type must not be empty")


@dataclass(frozen=True, slots=True)
class TFTConfig:
    """Configuration for the TFT forecasting wrapper."""

    horizon: int = 168
    step_hours: int = 1
    target_column: str = "siips_score"
    service_column: str = "service_id"
    time_column: str = "timestamp"
    static_categoricals: tuple[str, ...] = ("service_id",)
    known_future_reals: tuple[str, ...] = (
        "planned_staff_redeployments",
        "scheduled_discharges",
        "scheduled_surgeries",
        "expected_transfers_in",
        "expected_transfers_out",
        "scheduled_admissions",
        "planned_procedures",
    )
    max_encoder_length: int = 336
    allow_fallback: bool = True
    model_version: str = "tft-moirai-ft-v1.0"
    # Real-backend training hyperparameters (CPU-friendly defaults)
    max_epochs: int = 8
    batch_size: int = 64
    learning_rate: float = 3e-2
    hidden_size: int = 32
    attention_head_size: int = 4
    dropout: float = 0.1
    hidden_continuous_size: int = 16
    limit_train_batches: int | float = 200
    limit_val_batches: int | float = 50
    gradient_clip_val: float = 0.1
    early_stopping_patience: int = 3

    def __post_init__(self) -> None:
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

    def fit(
        self,
        dataset: pd.DataFrame,
        config: TFTConfig,
        validation_dataset: pd.DataFrame | None = None,
    ) -> dict[str, float]:
        """Fit the backend and return training metrics."""
        ...


class PytorchForecastingTFTBackend:
    """Real adapter around ``pytorch-forecasting`` and Lightning."""

    name = "pytorch_forecasting_tft"

    def __init__(self) -> None:
        self._validate_dependency()
        self._model: Any = None
        self._training_dataset: Any = None
        self._last_config: TFTConfig | None = None

    @classmethod
    def from_artifacts(
        cls,
        *,
        checkpoint_path: Path,
        training_dataset_path: Path,
    ) -> PytorchForecastingTFTBackend:
        """Load a trained TFT checkpoint and its dataset encoders once for serving."""
        import pickle

        backend = cls()
        backend.load_checkpoint(checkpoint_path)
        with training_dataset_path.open("rb") as handle:
            backend._training_dataset = pickle.load(handle)
        return backend

    def load_checkpoint(self, checkpoint_path: Path) -> None:
        """Load model + training dataset from pickle bundle.

        Restores self._model, self._training_dataset, and self._last_config
        so that predict() can run without re-training.
        Raises FileNotFoundError if the bundle is missing.
        """
        import cloudpickle

        if not checkpoint_path.exists():
            raise FileNotFoundError(
                f"Model bundle not found at {checkpoint_path}. Run train_tft.py to generate it."
            )

        with checkpoint_path.open("rb") as handle:
            bundle = cloudpickle.load(handle)

        self._model = bundle["model"]
        self._training_dataset = bundle["training_dataset"]
        self._last_config = bundle.get("config")
        if hasattr(self._model, "eval"):
            self._model.eval()
        LOGGER.info(
            "tft_bundle_loaded",
            path=str(checkpoint_path),
            has_config=self._last_config is not None,
        )

    def fit(
        self,
        dataset: pd.DataFrame,
        config: TFTConfig,
        validation_dataset: pd.DataFrame | None = None,
    ) -> dict[str, float]:
        """Fit a pytorch-forecasting TFT model on the provided dataset."""
        import lightning as L
        from lightning.pytorch.callbacks import EarlyStopping
        from pytorch_forecasting import (  # type: ignore[import-untyped]
            TemporalFusionTransformer,
            TimeSeriesDataSet,
        )
        from pytorch_forecasting.data import GroupNormalizer  # type: ignore[import-untyped]
        from pytorch_forecasting.metrics import QuantileLoss  # type: ignore[import-untyped]

        self._configure_lightning_logging()
        train_frame, validation_frame = self._resolve_fit_frames(
            dataset=dataset,
            validation_dataset=validation_dataset,
            config=config,
        )
        prepared = self._prepare_dataframe(train_frame, config)
        max_prediction_length = config.horizon
        max_encoder_length = config.max_encoder_length

        training_cutoff = prepared["time_idx"].max() - max_prediction_length
        if training_cutoff < max_encoder_length // 2:
            raise ValueError("training dataset is too short for TFT encoder and horizon")

        training = TimeSeriesDataSet(
            prepared[prepared["time_idx"] <= training_cutoff],
            time_idx="time_idx",
            target=config.target_column,
            group_ids=[config.service_column],
            min_encoder_length=max_encoder_length // 2,
            max_encoder_length=max_encoder_length,
            min_prediction_length=1,
            max_prediction_length=max_prediction_length,
            static_categoricals=[config.service_column],
            time_varying_known_reals=list(config.known_future_reals) + ["time_idx"],
            time_varying_unknown_reals=[config.target_column],
            target_normalizer=GroupNormalizer(
                groups=[config.service_column],
                transformation="softplus",
            ),
            add_relative_time_idx=True,
            add_target_scales=True,
            add_encoder_length=True,
            allow_missing_timesteps=True,
        )

        validation_prepared, min_prediction_idx = self._prepare_validation_dataframe(
            train_frame=train_frame,
            validation_frame=validation_frame,
            config=config,
        )
        validation = TimeSeriesDataSet.from_dataset(
            training,
            validation_prepared,
            min_prediction_idx=min_prediction_idx,
            predict=False,
            stop_randomization=True,
        )
        if len(validation) < 2:
            raise ValueError("validation dataset produced fewer than two TFT samples")

        train_loader = training.to_dataloader(
            train=True, batch_size=config.batch_size, num_workers=0
        )
        val_loader = validation.to_dataloader(
            train=False,
            batch_size=config.batch_size * 2,
            num_workers=0,
            shuffle=False,
        )

        tft = TemporalFusionTransformer.from_dataset(
            training,
            learning_rate=config.learning_rate,
            hidden_size=config.hidden_size,
            attention_head_size=config.attention_head_size,
            dropout=config.dropout,
            hidden_continuous_size=config.hidden_continuous_size,
            output_size=7,
            loss=QuantileLoss(),
            log_interval=-1,
            reduce_on_plateau_patience=4,
        )

        early_stop = EarlyStopping(
            monitor="val_loss",
            min_delta=1e-4,
            patience=config.early_stopping_patience,
            verbose=False,
            mode="min",
        )

        trainer = L.Trainer(
            max_epochs=config.max_epochs,
            accelerator="cpu",
            gradient_clip_val=config.gradient_clip_val,
            callbacks=[early_stop],
            enable_checkpointing=False,
            enable_progress_bar=False,
            enable_model_summary=False,
            inference_mode=True,
            logger=False,
            limit_train_batches=config.limit_train_batches,
            limit_val_batches=config.limit_val_batches,
            num_sanity_val_steps=0,
        )

        LOGGER.info(
            "tft_training_started",
            backend=self.name,
            max_epochs=config.max_epochs,
            train_samples=len(training),
            val_samples=len(validation),
        )

        trainer.fit(tft, train_dataloaders=train_loader, val_dataloaders=val_loader)

        self._model = tft
        self._training_dataset = training
        self._last_config = config

        train_metrics = self._evaluate_loader(tft, train_loader)
        validation_metrics = self._evaluate_loader(tft, val_loader)

        LOGGER.info(
            "tft_training_completed",
            backend=self.name,
            train_mae=train_metrics["mae"],
            train_mape=train_metrics["mape"],
            validation_mae=validation_metrics["mae"],
            validation_mape=validation_metrics["mape"],
        )

        return {
            "train_mae": train_metrics["mae"],
            "train_mape": train_metrics["mape"],
            "validation_mae": validation_metrics["mae"],
            "validation_mape": validation_metrics["mape"],
        }

    def save_bundle(self, bundle_path: Path) -> None:
        """Save model + training dataset as pickle bundle for serving.

        This is the serving-ready artifact: model weights + the TimeSeriesDataSet
        template needed by pytorch-forecasting to interpret incoming dataframes.
        Lightning .ckpt files alone are insufficient because the dataset schema
        is not embedded reliably across pytorch-forecasting versions.
        """
        import cloudpickle  # type: ignore[import-untyped]

        if self._model is None or self._training_dataset is None:
            raise RuntimeError("Cannot save bundle: model not trained")

        bundle = {
            "model": self._model,
            "training_dataset": self._training_dataset,
            "config": self._last_config,
        }
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        with bundle_path.open("wb") as handle:
            cloudpickle.dump(bundle, handle)
        LOGGER.info(
            "tft_bundle_saved",
            path=str(bundle_path),
            size_mb=round(bundle_path.stat().st_size / 1e6, 2),
        )

    def predict(
        self,
        history: pd.DataFrame,
        future_covariates: pd.DataFrame,
        config: TFTConfig,
    ) -> TFTForecast:
        """Predict with the trained TFT model."""
        try:
            return self.predict_fast(history, future_covariates, config)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("tft_fast_path_failed_using_dataloader", error=str(exc))
            return self._predict_with_dataloader(history, future_covariates, config)

    @torch.inference_mode()
    def predict_fast(
        self,
        history: pd.DataFrame,
        future_covariates: pd.DataFrame,
        config: TFTConfig,
    ) -> TFTForecast:
        """Run a single forecast without Lightning ``Trainer`` or DataLoader setup."""
        from pytorch_forecasting import TimeSeriesDataSet

        if self._model is None:
            raise RuntimeError("model must be trained before predict()")

        model = self._model
        model.eval()
        prepared = self._prepare_dataframe(history, config, future_covariates)
        if self._training_dataset is not None:
            predict_ds = TimeSeriesDataSet.from_dataset(
                self._training_dataset,
                prepared,
                predict=True,
                stop_randomization=True,
            )
        else:
            dataset_parameters = self._checkpoint_dataset_parameters(model)
            if dataset_parameters is None:
                raise RuntimeError("trained TFT has no dataset parameters for serving")
            predict_ds = TimeSeriesDataSet.from_parameters(
                dataset_parameters,
                prepared,
                predict=True,
                stop_randomization=True,
            )
        sample_x, _sample_y = predict_ds[0]
        batch_x = self._batch_timeseries_sample(sample_x, self._model_device(model))
        raw = model(batch_x)

        prediction_tensor = self._prediction_tensor(raw)
        forecast_array = self._median_forecast(prediction_tensor, config)

        return TFTForecast(
            value=float(forecast_array[-1]),
            horizon_values=forecast_array,
            top_features=list(config.known_future_reals[:3]),
            model_version=config.model_version,
        )

    def _predict_with_dataloader(
        self,
        history: pd.DataFrame,
        future_covariates: pd.DataFrame,
        config: TFTConfig,
    ) -> TFTForecast:
        """Compatibility prediction path for unusual pytorch-forecasting releases."""
        from pytorch_forecasting import TimeSeriesDataSet

        if self._model is None:
            raise RuntimeError("model must be trained before predict()")

        prepared = self._prepare_dataframe(history, config, future_covariates)
        if self._training_dataset is not None:
            predict_ds = TimeSeriesDataSet.from_dataset(
                self._training_dataset,
                prepared,
                predict=True,
                stop_randomization=True,
            )
        else:
            dataset_parameters = self._checkpoint_dataset_parameters(self._model)
            if dataset_parameters is None:
                raise RuntimeError("trained TFT has no dataset parameters for serving")
            predict_ds = TimeSeriesDataSet.from_parameters(
                dataset_parameters,
                prepared,
                predict=True,
                stop_randomization=True,
            )
        predict_loader = predict_ds.to_dataloader(
            train=False,
            batch_size=64,
            num_workers=0,
            shuffle=False,
        )

        with torch.no_grad():
            raw = self._model.predict(predict_loader, mode="raw", return_x=True)

        prediction_tensor = raw.output.prediction[..., 3]
        forecast_array = self._median_forecast(prediction_tensor, config)

        top_features = self._extract_top_features(self._model, raw, config)

        return TFTForecast(
            value=float(forecast_array[-1]),
            horizon_values=forecast_array,
            top_features=top_features,
            model_version=config.model_version,
        )

    @staticmethod
    def _checkpoint_dataset_parameters(model: Any) -> dict[str, Any] | None:
        parameters = getattr(model, "dataset_parameters", None)
        if isinstance(parameters, dict):
            return parameters
        hparams = getattr(model, "hparams", None)
        if hparams is None:
            return None
        hparams_parameters = getattr(hparams, "dataset_parameters", None)
        if isinstance(hparams_parameters, dict):
            return hparams_parameters
        if isinstance(hparams, dict):
            raw_parameters = hparams.get("dataset_parameters")
            if isinstance(raw_parameters, dict):
                return raw_parameters
        return None

    @staticmethod
    def _model_device(model: Any) -> torch.device:
        try:
            return cast(torch.device, next(model.parameters()).device)
        except StopIteration:
            return torch.device("cpu")

    @classmethod
    def _batch_timeseries_sample(
        cls,
        sample: dict[str, Any],
        device: torch.device,
    ) -> dict[str, torch.Tensor]:
        encoder_length = int(sample["encoder_length"])
        decoder_length = int(sample["decoder_length"])
        x_cat = cls._as_tensor(sample["x_cat"], device=device, dtype=torch.long)
        x_cont = cls._as_tensor(sample["x_cont"], device=device, dtype=torch.float32)
        encoder_target = cls._as_tensor(
            sample["encoder_target"],
            device=device,
            dtype=torch.float32,
        )
        groups = cls._as_tensor(sample["groups"], device=device, dtype=torch.long)
        target_scale = cls._as_tensor(sample["target_scale"], device=device, dtype=torch.float32)
        time_idx_start = int(cls._as_tensor(sample["encoder_time_idx_start"], device=device).item())
        decoder_time_idx = torch.arange(
            time_idx_start + encoder_length,
            time_idx_start + encoder_length + decoder_length,
            device=device,
            dtype=torch.long,
        )

        return {
            "encoder_cat": x_cat[:encoder_length].unsqueeze(0),
            "encoder_cont": x_cont[:encoder_length].unsqueeze(0),
            "encoder_target": encoder_target[:encoder_length].unsqueeze(0),
            "encoder_lengths": torch.tensor([encoder_length], device=device, dtype=torch.long),
            "decoder_cat": x_cat[encoder_length : encoder_length + decoder_length].unsqueeze(0),
            "decoder_cont": x_cont[encoder_length : encoder_length + decoder_length].unsqueeze(0),
            "decoder_target": torch.zeros((1, decoder_length), device=device, dtype=torch.float32),
            "decoder_lengths": torch.tensor([decoder_length], device=device, dtype=torch.long),
            "decoder_time_idx": decoder_time_idx.unsqueeze(0),
            "groups": groups.reshape(1, -1),
            "target_scale": target_scale.reshape(1, -1),
        }

    @staticmethod
    def _as_tensor(
        value: Any,
        *,
        device: torch.device,
        dtype: torch.dtype | None = None,
    ) -> torch.Tensor:
        tensor = value if isinstance(value, torch.Tensor) else torch.as_tensor(value)
        if dtype is not None:
            tensor = tensor.to(dtype=dtype)
        return tensor.to(device)

    @staticmethod
    def _prediction_tensor(raw: Any) -> torch.Tensor:
        prediction = raw["prediction"] if isinstance(raw, dict) else raw.prediction
        if not isinstance(prediction, torch.Tensor):
            raise TypeError("TFT forward output did not contain a prediction tensor")
        return prediction

    @staticmethod
    def _median_forecast(
        prediction_tensor: torch.Tensor,
        config: TFTConfig,
    ) -> npt.NDArray[np.float64]:
        if prediction_tensor.ndim == 3:
            median_tensor = prediction_tensor[..., 3]
        elif prediction_tensor.ndim == 2:
            median_tensor = prediction_tensor
        else:
            median_tensor = prediction_tensor.reshape(1, -1)
        forecast_array = median_tensor[-1].detach().cpu().numpy().astype(float)
        if forecast_array.shape[0] < config.horizon:
            pad_value = float(forecast_array[-1]) if forecast_array.size else 0.0
            padding = np.full(config.horizon - forecast_array.shape[0], pad_value, dtype=float)
            forecast_array = np.concatenate([forecast_array, padding])
        return forecast_array[: config.horizon]

    def _prepare_dataframe(
        self,
        df: pd.DataFrame,
        config: TFTConfig,
        future_covariates: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Prepare a dataframe for ``pytorch_forecasting``.

        Adds a per-group ``time_idx`` integer column, ensures dtypes, and
        zero-fills missing future-known features. Optionally appends rows
        from ``future_covariates`` after the last observed timestamp.
        """
        if config.target_column not in df.columns:
            raise ValueError(f"target column '{config.target_column}' missing")

        prepared = df.copy()
        prepared[config.time_column] = pd.to_datetime(prepared[config.time_column])
        prepared = prepared.sort_values([config.service_column, config.time_column])
        prepared[config.service_column] = prepared[config.service_column].astype(str)
        prepared[config.target_column] = prepared[config.target_column].astype(float)

        for feature in config.known_future_reals:
            if feature not in prepared.columns:
                prepared[feature] = 0.0
            else:
                prepared[feature] = pd.to_numeric(prepared[feature], errors="coerce").fillna(0.0)

        if future_covariates is not None and not future_covariates.empty:
            extra = future_covariates.copy()
            extra[config.time_column] = pd.to_datetime(extra[config.time_column])
            # Attach future covariates to each known service in history
            services = prepared[config.service_column].unique()
            blocks: list[pd.DataFrame] = [prepared]
            for service in services:
                tail = prepared[prepared[config.service_column] == service].iloc[-1]
                future_block = extra.copy()
                future_block[config.service_column] = service
                future_block[config.target_column] = float(tail[config.target_column])
                blocks.append(future_block)
            prepared = pd.concat(blocks, ignore_index=True)
            prepared = prepared.sort_values([config.service_column, config.time_column])

        prepared["time_idx"] = prepared.groupby(config.service_column).cumcount().astype(int)
        return prepared.reset_index(drop=True)

    def _resolve_fit_frames(
        self,
        *,
        dataset: pd.DataFrame,
        validation_dataset: pd.DataFrame | None,
        config: TFTConfig,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Return explicit train/validation frames, deriving a holdout when needed."""
        if validation_dataset is not None:
            if validation_dataset.empty:
                raise ValueError("validation_dataset must not be empty")
            return dataset.reset_index(drop=True), validation_dataset.reset_index(drop=True)

        ordered = dataset.sort_values(config.time_column).reset_index(drop=True)
        minimum_validation_rows = max(config.horizon * 2, config.max_encoder_length)
        if len(ordered) <= minimum_validation_rows + config.max_encoder_length:
            validation_frame = ordered.tail(minimum_validation_rows).reset_index(drop=True)
            train_frame = ordered.iloc[: -len(validation_frame)].reset_index(drop=True)
        else:
            validation_start = max(
                int(len(ordered) * 0.85),
                len(ordered) - minimum_validation_rows,
            )
            validation_frame = ordered.iloc[validation_start:].reset_index(drop=True)
            train_frame = ordered.iloc[:validation_start].reset_index(drop=True)
        if train_frame.empty:
            raise ValueError("dataset is too short to derive an internal validation split")
        return train_frame, validation_frame

    def _prepare_validation_dataframe(
        self,
        *,
        train_frame: pd.DataFrame,
        validation_frame: pd.DataFrame,
        config: TFTConfig,
    ) -> tuple[pd.DataFrame, int]:
        """Append encoder history to validation data and return its first target index."""
        history = (
            train_frame.sort_values([config.service_column, config.time_column])
            .groupby(config.service_column, group_keys=False)
            .tail(config.max_encoder_length)
            .copy()
        )
        history["_carepredict_split"] = "history"
        validation = validation_frame.copy()
        validation["_carepredict_split"] = "validation"
        combined = pd.concat([history, validation], ignore_index=True)
        prepared = self._prepare_dataframe(combined, config)
        validation_rows = prepared[prepared["_carepredict_split"] == "validation"]
        if validation_rows.empty:
            raise ValueError("validation frame did not survive TFT preparation")
        return prepared, int(validation_rows["time_idx"].min())

    @torch.inference_mode()
    def _evaluate_loader(self, model: Any, dataloader: Any) -> dict[str, float]:
        """Evaluate MAE/MAPE without constructing a Lightning prediction loop."""
        device = self._model_device(model)
        errors: list[torch.Tensor] = []
        percentage_errors: list[torch.Tensor] = []
        model.eval()

        for batch_x, batch_y in dataloader:
            moved_x = self._move_tensor_tree(batch_x, device)
            target = self._target_tensor(batch_y).to(device=device, dtype=torch.float32)
            raw = model(moved_x)
            prediction = self._prediction_tensor(raw)
            if prediction.ndim == 3:
                prediction = prediction[..., 3]
            preds_t = prediction.float().reshape(-1)
            actuals_t = target.reshape(-1)
            min_len = min(preds_t.numel(), actuals_t.numel())
            preds_t = preds_t[:min_len]
            actuals_t = actuals_t[:min_len]
            batch_errors = torch.abs(preds_t - actuals_t)
            errors.append(batch_errors.detach().cpu())
            percentage_errors.append(
                (batch_errors / torch.clamp(torch.abs(actuals_t), min=1.0)).detach().cpu()
            )

        if not errors:
            raise ValueError("cannot evaluate an empty dataloader")
        return {
            "mae": float(torch.mean(torch.cat(errors)).item()),
            "mape": float(torch.mean(torch.cat(percentage_errors)).item()),
        }

    @classmethod
    def _move_tensor_tree(cls, value: Any, device: torch.device) -> Any:
        if isinstance(value, torch.Tensor):
            return value.to(device)
        if isinstance(value, dict):
            return {key: cls._move_tensor_tree(item, device) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._move_tensor_tree(item, device) for item in value]
        if isinstance(value, tuple):
            return tuple(cls._move_tensor_tree(item, device) for item in value)
        return value

    @staticmethod
    def _target_tensor(batch_y: Any) -> torch.Tensor:
        target = batch_y[0] if isinstance(batch_y, (list, tuple)) else batch_y
        if not isinstance(target, torch.Tensor):
            raise TypeError("TFT dataloader target is not a tensor")
        return target

    @staticmethod
    def _configure_lightning_logging() -> None:
        for logger_name in ("lightning", "lightning.pytorch", "pytorch_lightning"):
            logging.getLogger(logger_name).setLevel(logging.WARNING)
        warnings.filterwarnings(
            "ignore",
            message=".*does not have many workers.*",
            module="lightning.*",
        )
        warnings.filterwarnings(
            "ignore",
            message="Attribute '.*' is an instance of `nn.Module`.*",
            module="lightning.*",
        )

    @staticmethod
    def _extract_top_features(model: Any, raw: Any, config: TFTConfig) -> list[str]:
        """Best-effort top-feature extraction from TFT variable selection."""
        try:
            interpretation = model.interpret_output(raw.output, reduction="sum")
            encoder_imp = interpretation.get("encoder_variables")
            decoder_imp = interpretation.get("decoder_variables")
            scores: dict[str, float] = {}
            if encoder_imp is not None and hasattr(encoder_imp, "items"):
                for name, value in encoder_imp.items():
                    scores[str(name)] = scores.get(str(name), 0.0) + float(value)
            if decoder_imp is not None and hasattr(decoder_imp, "items"):
                for name, value in decoder_imp.items():
                    scores[str(name)] = scores.get(str(name), 0.0) + float(value)
            if scores:
                ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
                return [name for name, _ in ranked[:3]]
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("tft_attention_extraction_failed", error=str(exc))
        return list(config.known_future_reals[:3])

    @staticmethod
    def _validate_dependency() -> None:
        missing: list[str] = []
        for module_name in ("pytorch_forecasting", "lightning", "torch"):
            try:
                __import__(module_name)
            except ImportError:
                missing.append(module_name)
        if missing:
            raise RuntimeError(
                f"pytorch-forecasting backend unavailable; missing: {', '.join(missing)}"
            )


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
        target = history[config.target_column].astype(float).dropna()
        if target.empty:
            raise ValueError("history target column must contain at least one non-null value")

        current = float(target.iloc[-1])
        trend = self._recent_hourly_trend(target)
        horizon_values: list[float] = []
        feature_scores = dict.fromkeys(config.known_future_reals, 0.0)

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

    def fit(
        self,
        dataset: pd.DataFrame,
        config: TFTConfig,
        validation_dataset: pd.DataFrame | None = None,
    ) -> dict[str, float]:
        target = dataset[config.target_column].astype(float)
        shifted = target.shift(config.horizon).fillna(target.expanding().mean())
        mae = float((target - shifted).abs().mean())
        mape = float(((target - shifted).abs() / target.clip(lower=1.0)).mean())
        metrics = {"train_mae": mae, "train_mape": mape}
        if validation_dataset is not None:
            validation_target = validation_dataset[config.target_column].astype(float)
            validation_shifted = validation_target.shift(config.horizon).fillna(
                validation_target.expanding().mean()
            )
            metrics["validation_mae"] = float((validation_target - validation_shifted).abs().mean())
            metrics["validation_mape"] = float(
                (
                    (validation_target - validation_shifted).abs()
                    / validation_target.clip(lower=1.0)
                ).mean()
            )
        return metrics

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
        return getattr(self._backend, "name", self._backend.__class__.__name__)

    def predict(
        self,
        history: pd.DataFrame,
        future_covariates: pd.DataFrame | None = None,
        interventions: list[FutureIntervention] | None = None,
    ) -> TFTForecast:
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

    def fit(
        self,
        dataset: pd.DataFrame,
        validation_dataset: pd.DataFrame | None = None,
    ) -> dict[str, float]:
        self._validate_history(dataset)
        if validation_dataset is not None:
            self._validate_history(validation_dataset)
        return self._backend.fit(dataset, self.config, validation_dataset)

    def load_checkpoint(self, checkpoint_path: Path) -> None:
        """Load a serving TFT checkpoint and activate the real backend.

        ``checkpoint_path`` must point to a pytorch-lightning ``.ckpt`` created
        from ``pytorch_forecasting.TemporalFusionTransformer``. If the facade was
        initially using the fallback because optional dependencies were missing,
        this method attempts to instantiate the real backend before loading.
        """
        backend = (
            self._backend
            if isinstance(self._backend, PytorchForecastingTFTBackend)
            else PytorchForecastingTFTBackend()
        )
        backend.load_checkpoint(checkpoint_path)
        self._backend = backend

    def predict_dataframe(
        self,
        frame: pd.DataFrame,
        history_buffer: pd.DataFrame | None = None,
    ) -> pd.Series:
        """Rolling 1-step predictions over ``frame``.

        For each row in ``frame``, predicts the target value using all data up to
        the row's timestamp. Predictions are aligned with ``frame`` index. Useful
        for backtesting and producing series to calibrate conformal intervals.
        """
        self._validate_history(frame)
        if history_buffer is not None:
            self._validate_history(history_buffer)
            combined = pd.concat([history_buffer, frame], ignore_index=True)
        else:
            combined = frame.copy()

        col = self.config.time_column
        combined[col] = pd.to_datetime(combined[col], utc=True)
        combined = combined.sort_values([self.config.service_column, col])

        predictions: list[float] = []
        frame_timestamps = pd.to_datetime(frame[col], utc=True).values
        frame_services = frame[self.config.service_column].astype(str).values

        for ts, service in zip(frame_timestamps, frame_services, strict=True):
            ts_pd = pd.Timestamp(ts)
            if ts_pd.tzinfo is None:
                ts_pd = ts_pd.tz_localize("UTC")
            sub = combined[
                (combined[self.config.service_column].astype(str) == str(service))
                & (combined[col] < ts_pd)
            ].tail(self.config.max_encoder_length * 2)
            if sub.empty or len(sub) < self.config.max_encoder_length // 2:
                last_value = float(
                    combined[combined[self.config.service_column].astype(str) == str(service)][
                        self.config.target_column
                    ]
                    .dropna()
                    .iloc[-1]
                    if not combined.empty
                    else 0.0
                )
                predictions.append(last_value)
                continue
            try:
                forecast = self._backend.predict(
                    sub,
                    build_future_covariates(
                        timestamp=ts_pd - pd.Timedelta(hours=1),
                        interventions=[],
                        config=self.config,
                    ),
                    self.config,
                )
                predictions.append(float(forecast.horizon_values[0]))
            except Exception as exc:  # noqa: BLE001
                LOGGER.debug("predict_dataframe_step_failed", error=str(exc))
                predictions.append(float(sub[self.config.target_column].iloc[-1]))

        return pd.Series(predictions, index=frame.index, name="prediction")

    def _build_backend(self) -> TFTBackend:
        try:
            return PytorchForecastingTFTBackend()
        except RuntimeError as exc:
            if not self.config.allow_fallback:
                raise
            LOGGER.warning("tft_backend_unavailable_using_fallback", error=str(exc))
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
    if base_timestamp.tzinfo is None:
        base_timestamp = base_timestamp.tz_localize("UTC")
    else:
        base_timestamp = base_timestamp.tz_convert("UTC")
    for step in range(1, config.horizon + 1):
        bucket_start = base_timestamp + pd.Timedelta(hours=step * config.step_hours)
        row: dict[str, object] = {
            "timestamp": bucket_start,
            **dict.fromkeys(config.known_future_reals, 0),
        }
        for intervention in interventions:
            scheduled_at = pd.Timestamp(intervention.scheduled_at)
            if scheduled_at.tzinfo is None:
                scheduled_at = scheduled_at.tz_localize("UTC")
            else:
                scheduled_at = scheduled_at.tz_convert("UTC")
            if scheduled_at.floor("h") == bucket_start.floor("h"):
                feature_name = _intervention_to_feature(intervention.intervention_type)
                if feature_name in row:
                    current_count = row.get(feature_name, 0)
                    safe_count = current_count if isinstance(current_count, int) else 0
                    row[feature_name] = safe_count + intervention.count
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
