"""Tests for the CarePredict TFT wrapper."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
import torch

from services.ml.models.tft_model import (
    CarePredictTFT,
    FutureIntervention,
    InterpretableTFTFallback,
    PytorchForecastingTFTBackend,
    TFTConfig,
    build_future_covariates,
)


def _history(periods: int = 24) -> pd.DataFrame:
    hour = np.arange(periods, dtype=float)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=periods, freq="h", tz="UTC"),
            "service_id": ["urg-001"] * periods,
            "hospital_profile": ["acute"] * periods,
            "siips_score": 40.0 + hour * 0.1 + 2.0 * np.sin(hour / 24.0 * 2.0 * np.pi),
            "patient_count": 18.0 + hour * 0.02 + 1.5 * np.sin(hour / 24.0 * 2.0 * np.pi),
        }
    )


def test_tft_predict_returns_value_and_attention_features() -> None:
    model = CarePredictTFT(
        config=TFTConfig(horizon=12),
        backend=InterpretableTFTFallback(),
    )
    interventions = [
        FutureIntervention(
            intervention_type="discharge",
            scheduled_at=datetime(2026, 1, 2, 3, tzinfo=UTC),
            count=3,
        ),
        FutureIntervention(
            intervention_type="surgery",
            scheduled_at=datetime(2026, 1, 2, 6, tzinfo=UTC),
            count=2,
        ),
    ]

    forecast = model.predict(_history(), interventions=interventions)

    assert forecast.horizon_values.shape == (12,)
    assert isinstance(forecast.value, float)
    assert forecast.top_features[:2] == ["scheduled_discharges", "scheduled_surgeries"]
    assert forecast.model_version == "tft-moirai-ft-v1.0"


def test_build_future_covariates_maps_intervention_types() -> None:
    config = TFTConfig(horizon=12)
    covariates = build_future_covariates(
        timestamp=pd.Timestamp("2026-01-01T23:00:00Z"),
        interventions=[
            FutureIntervention(
                intervention_type="transfer_in",
                scheduled_at=datetime(2026, 1, 2, 1, tzinfo=UTC),
                count=4,
            )
        ],
        config=config,
    )

    assert len(covariates) == 12
    assert covariates["expected_transfers_in"].sum() == 4


def test_tft_rejects_missing_history_columns() -> None:
    model = CarePredictTFT()

    with pytest.raises(ValueError, match="missing required columns"):
        model.predict(pd.DataFrame({"siips_score": [1.0]}))


def test_tft_fit_returns_baseline_metrics() -> None:
    model = CarePredictTFT(backend=InterpretableTFTFallback())

    metrics = model.fit(_history())

    assert "train_mae" in metrics
    assert "train_mape" in metrics


def test_default_siips_target_matches_explicit_siips_target() -> None:
    frame = _history()
    default_model = CarePredictTFT(backend=InterpretableTFTFallback())
    explicit_model = CarePredictTFT(
        config=TFTConfig(target_column="siips_score"),
        backend=InterpretableTFTFallback(),
    )

    assert default_model.config == explicit_model.config
    assert default_model.fit(frame) == explicit_model.fit(frame)
    np.testing.assert_array_equal(
        default_model.predict(frame).horizon_values,
        explicit_model.predict(frame).horizon_values,
    )


@pytest.mark.parametrize("target_column", ["siips_score", "patient_count"])
def test_real_tft_backend_fits_and_forecasts_any_target(target_column: str) -> None:
    torch.manual_seed(0)
    frame = _history(periods=192)
    train = frame.iloc[:144].reset_index(drop=True)
    validation = frame.iloc[144:].reset_index(drop=True)
    config = TFTConfig(
        target_column=target_column,
        horizon=4,
        max_encoder_length=24,
        max_epochs=1,
        batch_size=32,
        learning_rate=1e-2,
        hidden_size=8,
        attention_head_size=1,
        dropout=0.0,
        hidden_continuous_size=4,
        limit_train_batches=1,
        limit_val_batches=1,
        early_stopping_patience=1,
    )
    model = CarePredictTFT(config=config, backend=PytorchForecastingTFTBackend())

    metrics = model.fit(train, validation_dataset=validation)
    forecast = model.predict(train.tail(config.max_encoder_length * 2))

    assert model.config.target_column == target_column
    assert all(np.isfinite(value) for value in metrics.values())
    assert forecast.horizon_values.shape == (config.horizon,)
    assert np.isfinite(forecast.horizon_values).all()
