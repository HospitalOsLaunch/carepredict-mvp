"""Tests for the shared v2 forecast inference path."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import torch
from torch import Tensor, nn

from services.ml.forecasting.v2_forecast import (
    ensure_hospitalos_importable,
    load_v2_forecast_artifacts,
    predict_v2_from_history,
    v2_forecast_history_length,
)

ARTIFACT_DIR = Path("artifacts/v2_forecast_multi")


def legacy_eval_predict_from_history(model: nn.Module, history: Tensor, origin: datetime) -> Tensor:
    """Reference copy of the pre-extraction eval_v2 forecast routine."""
    ensure_hospitalos_importable()
    from hospitalos.dynamics.jepa_rssm import calendar_encoding, symexp
    from hospitalos.training.train_v2_forecast import build_calendar_features

    with torch.inference_mode():
        z = model.encode_series(history)
        states = model.unroll(z)
        origin_features = states["features"][:, -1:, :]
        if model.forecast_head[0].in_features == origin_features.shape[-1] + 2:
            day = torch.tensor([float(origin.weekday())], dtype=torch.float32)
            hour = torch.zeros(1, dtype=torch.float32)
            origin_calendar = calendar_encoding(hour, day)[:, -2:].reshape(1, 1, 2)
        else:
            calendar = build_calendar_features(origin - timedelta(hours=167), 168).unsqueeze(0)
            origin_calendar = calendar[:, -1:, :]
        forecast_input = torch.cat([origin_features, origin_calendar], dim=-1)
        forecast = symexp(model.forecast_head(forecast_input))
        return forecast[0, 0, :].detach().cpu()


@pytest.mark.skipif(not ARTIFACT_DIR.exists(), reason="v2 forecast artifacts are unavailable")
def test_shared_predict_matches_legacy_eval_path_exactly() -> None:
    """The serving helper must preserve the eval forecast implementation exactly."""
    artifacts = load_v2_forecast_artifacts(ARTIFACT_DIR)
    length = v2_forecast_history_length(artifacts)
    values = torch.linspace(0.0, 1.0, steps=length * 7, dtype=torch.float32)
    history = values.reshape(1, length, 7)
    origin = datetime(2025, 7, 8, tzinfo=UTC)

    torch.manual_seed(0)
    expected = legacy_eval_predict_from_history(artifacts.model, history, origin)
    torch.manual_seed(0)
    actual = predict_v2_from_history(artifacts.model, history, origin)

    assert torch.equal(actual, expected)


@pytest.mark.skipif(not ARTIFACT_DIR.exists(), reason="v2 forecast artifacts are unavailable")
def test_shared_history_length_matches_daily_eval_origin_state() -> None:
    """Daily patch artifacts use 120 hourly feature rows to extract state d=4."""
    artifacts = load_v2_forecast_artifacts(ARTIFACT_DIR)

    assert artifacts.model.patcher.proj.weight.shape == (256, 168)
    assert v2_forecast_history_length(artifacts) == 120
