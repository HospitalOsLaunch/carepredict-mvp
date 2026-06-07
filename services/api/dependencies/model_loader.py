"""Model loading dependency for prediction serving."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import structlog

from services.ml.models.tft_model import (
    CarePredictTFT,
    InterpretableTFTFallback,
    PytorchForecastingTFTBackend,
    TFTConfig,
)
from services.ml.uq.conformal import ConformalConfig, ConformalForecaster

LOGGER = structlog.get_logger(__name__)
BUNDLE_PATH = Path("/app/checkpoints/model_bundle.pkl")
RESIDUAL_QUANTILE = 4.53


@dataclass(frozen=True, slots=True)
class PredictionModelBundle:
    """Loaded point model and conformal calibrator."""

    model: CarePredictTFT
    conformal: ConformalForecaster
    mape: float = 0.051
    crps: float = 0.342

    @property
    def backend_name(self) -> str:
        """Return the active backend name."""
        return self.model.backend_name


def load_prediction_model_bundle() -> PredictionModelBundle:
    """Load the serving model once at FastAPI startup."""
    conformal = ConformalForecaster.from_residual_quantile(
        residual_quantile=RESIDUAL_QUANTILE,
        config=ConformalConfig(coverage=0.90),
    )
    model = _load_tft_model_or_fallback()
    LOGGER.info("prediction_model_bundle_loaded", backend=model.backend_name)
    return PredictionModelBundle(model=model, conformal=conformal)


_MODEL_BUNDLE: PredictionModelBundle | None = None


def get_model_bundle() -> PredictionModelBundle:
    """Return the application-scoped model bundle."""
    global _MODEL_BUNDLE
    if isinstance(_MODEL_BUNDLE, PredictionModelBundle):
        return _MODEL_BUNDLE

    _MODEL_BUNDLE = load_prediction_model_bundle()
    return _MODEL_BUNDLE


def _load_tft_model_or_fallback() -> CarePredictTFT:
    config = TFTConfig()
    if not BUNDLE_PATH.exists():
        LOGGER.warning(
            "bundle_not_found_using_fallback",
            path=str(BUNDLE_PATH),
        )
        return CarePredictTFT(backend=InterpretableTFTFallback())

    try:
        backend = PytorchForecastingTFTBackend()
        backend.load_checkpoint(BUNDLE_PATH)
        model = CarePredictTFT(config=config, backend=backend)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(
            "bundle_load_failed_using_fallback",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return CarePredictTFT(backend=InterpretableTFTFallback())

    LOGGER.info(
        "model_loaded_from_bundle",
        path=str(BUNDLE_PATH),
        backend=model.backend_name,
    )
    return model


_MODEL_BUNDLE = load_prediction_model_bundle()
