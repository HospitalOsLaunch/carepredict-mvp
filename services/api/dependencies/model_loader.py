"""Model loading dependency for prediction serving."""

from __future__ import annotations

from dataclasses import dataclass

from services.ml.models.tft_model import CarePredictTFT
from services.ml.uq.conformal import ConformalConfig, ConformalForecaster


@dataclass(frozen=True, slots=True)
class PredictionModelBundle:
    """Loaded point model and conformal calibrator."""

    model: CarePredictTFT
    conformal: ConformalForecaster
    mape: float = 0.09
    crps: float = 0.12


def get_model_bundle() -> PredictionModelBundle:
    """Load latest champion model from MLflow.

    The current MVP returns a local model bundle; the registry boundary is kept
    here so pass 2 training can promote champion/challenger models without
    changing router code.
    """
    conformal = ConformalForecaster.from_residual_quantile(
        residual_quantile=6.0,
        config=ConformalConfig(coverage=0.90),
    )
    return PredictionModelBundle(model=CarePredictTFT(), conformal=conformal)
