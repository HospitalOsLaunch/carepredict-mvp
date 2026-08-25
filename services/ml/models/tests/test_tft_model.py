"""Tests for the CarePredict TFT wrapper."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from services.ml.models.tft_model import (
    CarePredictTFT,
    FutureIntervention,
    InterpretableTFTFallback,
    TFTConfig,
    build_future_covariates,
)


def _history() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=24, freq="h"),
            "service_id": ["urg-001"] * 24,
            "hospital_profile": ["acute"] * 24,
            "siips_score": [40.0 + hour * 0.1 for hour in range(24)],
        }
    )


def _fallback_model() -> CarePredictTFT:
    """Return the deterministic backend used by unit and contract tests."""
    return CarePredictTFT(backend=InterpretableTFTFallback())


def test_tft_predict_returns_value_and_attention_features() -> None:
    model = _fallback_model()
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

    assert forecast.horizon_values.shape == (model.config.horizon,)
    assert isinstance(forecast.value, float)
    assert forecast.top_features[:2] == ["scheduled_discharges", "scheduled_surgeries"]
    assert forecast.model_version == "tft-moirai-ft-v1.0"


def test_build_future_covariates_maps_intervention_types() -> None:
    config = TFTConfig()
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

    assert config.horizon == 168
    assert len(covariates) == config.horizon
    assert covariates["expected_transfers_in"].sum() == 4


def test_tft_rejects_missing_history_columns() -> None:
    model = _fallback_model()

    with pytest.raises(ValueError, match="missing required columns"):
        model.predict(pd.DataFrame({"siips_score": [1.0]}))


def test_tft_fit_returns_baseline_metrics() -> None:
    model = _fallback_model()

    metrics = model.fit(_history())

    assert "train_mae" in metrics
    assert "train_mape" in metrics
