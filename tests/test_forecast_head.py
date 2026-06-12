"""Tests for the day-boundary multi-horizon forecast head on JepaRSSM."""

from __future__ import annotations

import numpy as np
import pytest
import torch
from torch import Tensor, nn

from hospitalos.dynamics.jepa_rssm import (
    JepaRSSM,
    RSSMConfig,
    calendar_encoding,
    symexp,
    symlog,
)


class DailyDummyPatcher(nn.Module):
    """Aggregate 24 hourly samples into one daily token."""

    def forward(self, series: Tensor) -> Tensor:
        """Return one flattened token per complete day."""
        batch, time, channels = series.shape
        if time % 24 != 0:
            raise ValueError("test series length must be a multiple of 24")
        return series.reshape(batch, time // 24, 24 * channels)


class DummyEncoder(nn.Module):
    """Linear encoder accepting the frozen JEPA encoder signature."""

    def __init__(self, in_dim: int, emb_dim: int) -> None:
        super().__init__()
        self.proj = nn.Linear(in_dim, emb_dim, bias=False)

    def forward(self, tokens: Tensor, pos_idx: Tensor) -> Tensor:
        """Project tokens and ignore position indices."""
        del pos_idx
        return self.proj(tokens)


def make_model() -> JepaRSSM:
    """Create a compact forecast-capable RSSM for CPU tests."""
    cfg = RSSMConfig(
        emb_dim=8,
        deter=16,
        stoch_cat=4,
        stoch_classes=4,
        hidden=32,
        forecast_horizon=48,
    )
    return JepaRSSM(cfg, DummyEncoder(in_dim=96, emb_dim=8), DailyDummyPatcher())


def make_calendar(batch: int, hours: int) -> Tensor:
    """Build deterministic hourly calendar encodings for a test window."""
    hour_values = torch.arange(hours, dtype=torch.float32) % 24.0
    day_values = (
        torch.div(torch.arange(hours, dtype=torch.float32), 24.0, rounding_mode="floor") % 7.0
    )
    cal = calendar_encoding(hour_values, day_values)
    return cal.unsqueeze(0).expand(batch, -1, -1).contiguous()


def test_forecast_head_output_shape_daily_origins() -> None:
    """A 7-day window returns one 48h vector for valid daily origins d=1..4."""
    torch.manual_seed(0)
    np.random.seed(0)
    model = make_model()
    series = torch.randn(2, 168, 4, dtype=torch.float32)
    states = model.unroll(model.encode_series(series))

    out = model.forecast(states, make_calendar(batch=2, hours=168))

    assert out.shape == (2, 4, 48)
    assert torch.isfinite(out).all()
    assert model.forecast_head[0].in_features == model.cfg.deter + 16 + 2


def test_forecast_loss_finite_and_backward() -> None:
    """Forecast loss contributes gradients to the forecast head."""
    torch.manual_seed(0)
    np.random.seed(0)
    model = make_model()
    series = torch.randn(2, 168, 4, dtype=torch.float32)
    siips = torch.rand(2, 168, dtype=torch.float32) * 1000.0
    calendar = make_calendar(batch=2, hours=168)

    loss = model.training_step({"series": series, "siips": siips, "calendar": calendar}, 0)
    assert torch.isfinite(loss)
    loss.backward()

    assert any(param.grad is not None for param in model.forecast_head.parameters())


def test_forecast_at_day_boundary_unchanged_when_future_series_perturbed() -> None:
    """Forecast at day origin d is invariant to observations at hours >= (d+1)*24."""
    torch.manual_seed(0)
    np.random.seed(0)
    model = make_model()
    series = torch.randn(1, 168, 4, dtype=torch.float32)
    perturbed = series.clone()
    perturbed[:, 48:, :] = perturbed[:, 48:, :] + 1000.0
    calendar = make_calendar(batch=1, hours=168)

    torch.manual_seed(0)
    base_forecast = model.forecast(model.unroll(model.encode_series(series)), calendar)[:, 0, :]
    torch.manual_seed(0)
    perturbed_states = model.unroll(model.encode_series(perturbed))
    perturbed_forecast = model.forecast(perturbed_states, calendar)[:, 0, :]

    assert torch.allclose(base_forecast, perturbed_forecast, atol=1e-6)


def test_forecast_loss_rejects_partial_hourly_targets() -> None:
    """Daily forecast training asserts complete 24h target blocks are present."""
    torch.manual_seed(0)
    np.random.seed(0)
    model = make_model()
    series = torch.randn(1, 168, 4, dtype=torch.float32)
    siips = torch.rand(1, 167, dtype=torch.float32)

    with pytest.raises(ValueError, match="complete 24h blocks"):
        model.training_step(
            {"series": series, "siips": siips, "calendar": make_calendar(1, 168)},
            0,
        )


def test_symlog_symexp_round_trip() -> None:
    """Dreamer symlog and symexp are inverse transforms within tolerance."""
    values = torch.tensor([-1000.0, -10.0, 0.0, 10.0, 1000.0], dtype=torch.float32)

    restored = symexp(symlog(values))

    assert torch.allclose(restored, values, atol=1e-4, rtol=1e-5)


def test_calendar_encoding_is_deterministic() -> None:
    """Calendar features remain deterministic for identical hour/day tensors."""
    hours = torch.tensor([0.0, 6.0, 12.0, 18.0], dtype=torch.float32)
    days = torch.tensor([0.0, 1.0, 2.0, 3.0], dtype=torch.float32)

    first = calendar_encoding(hours, days)
    second = calendar_encoding(hours, days)

    assert first.shape == (4, 4)
    assert torch.allclose(first, second)
    assert torch.isfinite(first).all()
