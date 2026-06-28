"""Target-agnostic TFT training entrypoint tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from services.ml.models.tft_model import TFTConfig
from services.ml.training import train_tft
from services.ml.training.backtesting import BacktestMetrics
from services.ml.training.data_loader import temporal_split


def _frame() -> pd.DataFrame:
    size = 120
    index = np.arange(size, dtype=float)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01", periods=size, freq="h", tz="UTC"),
            "service_id": "urg-001",
            "hospital_profile": "acute",
            "siips_score": 1000.0 + index,
            "patient_count": 20.0 + index * 0.1,
        }
    )


@pytest.mark.parametrize("target_column", ["siips_score", "patient_count"])
def test_training_entrypoint_uses_configured_target_everywhere(
    target_column: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    frame = _frame()
    split = temporal_split(frame)
    seen: dict[str, object] = {}

    class FakeModel:
        backend_name = "target_agnostic_test_backend"
        _backend = object()

        def __init__(self, config: TFTConfig) -> None:
            self.config = config
            seen["model_target"] = config.target_column

        def fit(self, dataset: pd.DataFrame) -> dict[str, float]:
            seen["fit_values"] = dataset[self.config.target_column].to_numpy(copy=True)
            return {"train_mae": 0.0, "train_mape": 0.0}

        def predict_dataframe(
            self,
            dataset: pd.DataFrame,
            history_buffer: pd.DataFrame | None = None,
        ) -> pd.Series:
            del history_buffer
            return dataset[self.config.target_column].astype(float).rename("prediction")

    class FakeConformal:
        def calibrate(self, actual: pd.Series, predicted: pd.Series) -> None:
            np.testing.assert_array_equal(
                actual.to_numpy(),
                split.validation[target_column].to_numpy(),
            )
            np.testing.assert_array_equal(actual.to_numpy(), predicted.to_numpy())

        def predict_intervals(self, predicted: pd.Series) -> list[SimpleNamespace]:
            return [SimpleNamespace(lower=value, upper=value) for value in predicted]

    class FakeRegistry:
        def log_training_run(self, **kwargs: object) -> None:
            seen["registry_params"] = kwargs["params"]  # type: ignore[index]

    def fake_metrics(
        actual: pd.Series,
        predicted: pd.Series,
        lower: list[float],
        upper: list[float],
    ) -> BacktestMetrics:
        del lower, upper
        np.testing.assert_array_equal(actual.to_numpy(), split.test[target_column].to_numpy())
        np.testing.assert_array_equal(actual.to_numpy(), predicted.to_numpy())
        return BacktestMetrics(mae=0.0, mape=0.0, crps=0.0, coverage=1.0, ece=0.1)

    monkeypatch.setattr(train_tft, "load_synthetic_training_frame", lambda _path: frame)
    monkeypatch.setattr(train_tft, "CarePredictTFT", FakeModel)
    monkeypatch.setattr(train_tft, "ConformalForecaster", FakeConformal)
    monkeypatch.setattr(train_tft, "MLflowModelRegistry", FakeRegistry)
    monkeypatch.setattr(train_tft, "calculate_metrics", fake_metrics)

    train_tft.main(
        report_path=tmp_path / f"{target_column}.html",
        bundle_path=tmp_path / f"{target_column}.pkl",
        target_column=target_column,
    )

    assert seen["model_target"] == target_column
    np.testing.assert_array_equal(
        seen["fit_values"],
        split.train[target_column].to_numpy(),
    )
    assert seen["registry_params"]["target_column"] == target_column  # type: ignore[index]


def test_training_entrypoint_default_target_remains_siips() -> None:
    assert train_tft.main.__defaults__ is not None
    assert train_tft.main.__defaults__[-1] == "siips_score"
