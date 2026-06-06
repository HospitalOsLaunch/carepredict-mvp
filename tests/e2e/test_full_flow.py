"""End-to-end smoke test for pass 2 wiring."""

from __future__ import annotations

from pathlib import Path

from services.api.schemas.prediction import ChargePredictionResponse
from services.ml.models.tft_model import CarePredictTFT
from services.ml.training.data_loader import load_synthetic_training_frame
from services.ml.uq.conformal import ConformalForecaster


def test_full_flow_contract_smoke() -> None:
    frame = load_synthetic_training_frame(days=10)
    model = CarePredictTFT()
    forecast = model.predict(frame.tail(24))
    conformal = ConformalForecaster.from_residual_quantile(6.0)
    interval = conformal.predict_interval(forecast.value)
    response = ChargePredictionResponse(
        value=round(interval.value),
        lower_90=round(interval.lower),
        upper_90=round(interval.upper),
        coverage=0.90,
        mape=0.09,
        crps=0.12,
        model_version=forecast.model_version,
        attention_weights={"top_features": forecast.top_features},
    )

    assert response.lower_90 <= response.value <= response.upper_90
    assert Path("services/dashboard/src/App.tsx").exists()
