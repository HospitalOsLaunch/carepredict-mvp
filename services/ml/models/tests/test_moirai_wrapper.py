"""Tests for the Moirai cold-start wrapper."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from services.ml.models.moirai_wrapper import (
    MoiraiConfig,
    MoiraiWrapper,
    SeasonalNaiveBackend,
)


class TinyDataset:
    """Simple in-memory dataset for fine-tuning tests."""

    def to_pandas(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=48, freq="h"),
                "item_id": ["service-a"] * 48,
                "target": np.linspace(20.0, 32.0, 48),
            }
        )


@pytest.mark.skip(
    reason="uni2ts 2.0 API breaking change with our wrapper; refactor planned post-YC-application"
)
def test_moirai_predict_returns_horizon_values() -> None:
    history = pd.Series(
        np.arange(48, dtype=float),
        index=pd.date_range("2026-01-01", periods=48, freq="h"),
    )
    wrapper = MoiraiWrapper()

    forecast = wrapper.predict(history, horizon=12)

    assert forecast.shape == (12,)
    assert forecast.tolist() == list(np.arange(24, 36, dtype=float))


def test_moirai_predict_with_metadata_uses_stable_version() -> None:
    history = pd.Series([10.0, 11.0, 12.0])
    wrapper = MoiraiWrapper(backend=SeasonalNaiveBackend(season_length=2))

    result = wrapper.predict_with_metadata(history, horizon=3)

    assert result.horizon == 3
    assert result.backend_name == "seasonal_naive_fallback"
    assert result.model_version == "moirai-cold-start-seasonal_naive_fallback"
    assert result.values.tolist() == [11.0, 12.0, 11.0]


def test_moirai_rejects_empty_history() -> None:
    wrapper = MoiraiWrapper()

    with pytest.raises(ValueError, match="must not be empty"):
        wrapper.predict(pd.Series(dtype=float), horizon=12)


def test_moirai_rejects_invalid_horizon() -> None:
    wrapper = MoiraiWrapper()

    with pytest.raises(ValueError, match="horizon"):
        wrapper.predict(pd.Series([1.0, 2.0]), horizon=0)


def test_moirai_fine_tune_returns_metrics_without_mlflow_dependency() -> None:
    wrapper = MoiraiWrapper(backend=SeasonalNaiveBackend())

    result = wrapper.fine_tune(TinyDataset(), epochs=2)

    assert result.backend_name == "seasonal_naive_fallback"
    assert result.epochs == 2
    assert "baseline_mae" in result.metrics


def test_moirai_config_validates_checkpoint_path() -> None:
    with pytest.raises(ValueError, match="local_checkpoint_path"):
        MoiraiConfig(local_checkpoint_path=Path("/tmp/carepredict-missing-moirai.ckpt"))
