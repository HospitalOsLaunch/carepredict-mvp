from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
import torch

from rs_jepa.config import Stage1Config
from rs_jepa.ema import EMATargetEncoder, tau_schedule
from rs_jepa.encoder import ObservableEncoder, validate_observable_columns
from rs_jepa.masking import (
    apply_stage1_masks,
    block_temporal_mask,
    channel_mask,
    forecasting_mask,
    split_forecasting_window,
)

pytestmark = pytest.mark.rs_jepa


def tiny_cfg(**kwargs: Any) -> Stage1Config:
    cfg = Stage1Config(
        latent_dim=16,
        encoder_model_dim=16,
        encoder_depth=1,
        encoder_heads=2,
        encoder_ff_dim=32,
        encoder_dropout=0.0,
        encoder_max_steps=256,
        context_steps=24,
        horizons=(6, 12, 24),
        ema_ramp_steps=100,
    )
    return replace(cfg, **kwargs)


@pytest.mark.parametrize(("batch", "steps", "n_obs"), [(2, 18, 5), (4, 32, 9)])
def test_encoder_shape(batch: int, steps: int, n_obs: int) -> None:
    torch.manual_seed(0)
    cfg = tiny_cfg()
    encoder = ObservableEncoder(n_obs=n_obs, n_static=3, cfg=cfg)
    x = torch.randn(batch, steps, n_obs)
    static = torch.randn(batch, 3)
    out = encoder(x, static)
    assert out.shape == (batch, steps, cfg.latent_dim)


def test_encoder_determinism_depends_on_seed() -> None:
    cfg = tiny_cfg()
    x = torch.randn(2, 12, 4)
    static = torch.randn(2, 2)

    torch.manual_seed(123)
    first = ObservableEncoder(4, 2, cfg)
    out_first = first(x, static)

    torch.manual_seed(123)
    second = ObservableEncoder(4, 2, cfg)
    out_second = second(x, static)

    torch.manual_seed(124)
    third = ObservableEncoder(4, 2, cfg)
    out_third = third(x, static)

    assert torch.allclose(out_first, out_second)
    assert not torch.allclose(out_first, out_third)


def test_static_covariates_change_encoder_output() -> None:
    torch.manual_seed(0)
    cfg = tiny_cfg()
    encoder = ObservableEncoder(4, 2, cfg)
    x = torch.randn(2, 12, 4)
    static = torch.randn(2, 2)
    without_static = encoder(x, None)
    with_static = encoder(x, static)
    assert not torch.allclose(without_static, with_static)


def test_encoder_rejects_hidden_or_absolute_fields() -> None:
    with pytest.raises(ValueError, match="Colonnes interdites"):
        validate_observable_columns(["occupancy_ratio", "criticality", "acuity"])


def test_ema_target_parameters_are_distinct_and_frozen() -> None:
    online = ObservableEncoder(3, 1, tiny_cfg())
    ema = EMATargetEncoder(online)
    online_params = list(online.parameters())
    target_params = list(ema.target.parameters())
    assert len(online_params) == len(target_params)
    for online_param, target_param in zip(online_params, target_params, strict=True):
        assert online_param is not target_param
        assert not target_param.requires_grad


def test_ema_target_forward_is_stop_gradient() -> None:
    torch.manual_seed(0)
    online = ObservableEncoder(3, 1, tiny_cfg())
    ema = EMATargetEncoder(online)
    x = torch.randn(2, 8, 3, requires_grad=True)
    static = torch.randn(2, 1)
    target_latent = ema(x, static)
    assert not target_latent.requires_grad
    loss = (target_latent.detach() * x[:, :, :1]).sum()
    loss.backward()
    assert x.grad is not None
    assert all(param.grad is None for param in ema.target.parameters())


def test_ema_update_math_known_tensors() -> None:
    online = torch.nn.Linear(2, 2, bias=False)
    ema = EMATargetEncoder(online)
    with torch.no_grad():
        online.weight.fill_(3.0)
        ema.target.weight.fill_(1.0)
    ema.update_from(online, tau=0.9)
    assert torch.allclose(ema.target.weight, torch.full_like(ema.target.weight, 1.2))


def test_ema_update_moves_target_toward_online() -> None:
    online = torch.nn.Linear(3, 3)
    ema = EMATargetEncoder(online)
    with torch.no_grad():
        online.weight.fill_(2.0)
        online.bias.fill_(2.0)
        ema.target.weight.zero_()
        ema.target.bias.zero_()

    def distance() -> torch.Tensor:
        total = torch.tensor(0.0)
        param_pairs = zip(online.parameters(), ema.target.parameters(), strict=True)
        for online_param, target_param in param_pairs:
            total = total + torch.sum((online_param - target_param) ** 2)
        return torch.sqrt(total)

    before = distance()
    ema.update_from(online, tau=0.8)
    middle = distance()
    ema.update_from(online, tau=0.8)
    after = distance()
    assert middle < before
    assert after < middle


def test_tau_schedule_monotonic_ramp() -> None:
    values = [
        tau_schedule(step, ramp_steps=100, start=0.996, end=0.9999)
        for step in [0, 10, 50, 100, 200]
    ]
    assert values[0] == pytest.approx(0.996)
    assert values[-1] == pytest.approx(0.9999)
    assert values == sorted(values)


@pytest.mark.parametrize("horizon", [6, 12, 24])
def test_forecasting_mask_context_target_sizes_no_overlap_and_cover_window(horizon: int) -> None:
    cfg = tiny_cfg(context_steps=24, horizons=(6, 12, 24))
    context_idx, target_idx = forecasting_mask(24 + horizon, cfg, horizon=horizon)
    assert len(context_idx) == 24
    assert len(target_idx) == horizon
    assert set(context_idx.tolist()).isdisjoint(target_idx.tolist())
    assert torch.equal(torch.cat([context_idx, target_idx]), torch.arange(24 + horizon))


def test_split_forecasting_window_shapes() -> None:
    cfg = tiny_cfg(context_steps=10, horizons=(4,))
    x = torch.randn(3, 14, 5)
    context, target, _context_idx, _target_idx = split_forecasting_window(x, cfg, horizon=4)
    assert context.shape == (3, 10, 5)
    assert target.shape == (3, 4, 5)


def test_block_temporal_mask_fraction_and_contiguous_span() -> None:
    cfg = tiny_cfg(block_mask_min_frac=0.15, block_mask_max_frac=0.40)
    generator = torch.Generator().manual_seed(0)
    context = torch.ones(8, 40, 3)
    masked, mask = block_temporal_mask(context, cfg, generator=generator)
    frac = mask.float().mean(dim=1)
    assert torch.all(frac >= 0.15)
    assert torch.all(frac <= 0.40)
    for sample_mask in mask:
        indices = sample_mask.nonzero(as_tuple=False).flatten()
        assert len(indices) > 0
        assert torch.equal(indices, torch.arange(indices[0], indices[-1] + 1))
    assert torch.all(masked[mask] == 0)


def test_channel_mask_empirical_rate_and_whole_channel_zeroing() -> None:
    cfg = tiny_cfg(channel_mask_prob=0.20)
    generator = torch.Generator().manual_seed(0)
    x = torch.ones(512, 16, 10)
    masked, mask = channel_mask(x, cfg, generator=generator)
    rate = mask.float().mean().item()
    assert 0.16 <= rate <= 0.24
    for batch_idx, channel_idx in mask.nonzero(as_tuple=False):
        assert torch.all(masked[batch_idx, :, channel_idx] == 0)


def test_mask_composition_shapes_and_zero_consistency() -> None:
    cfg = tiny_cfg(context_steps=24, horizons=(12,), channel_mask_prob=0.25)
    generator = torch.Generator().manual_seed(12)
    x = torch.ones(4, 36, 6)
    result = apply_stage1_masks(x, cfg, horizon=12, generator=generator)
    assert result["context"].shape == (4, 24, 6)
    assert result["target"].shape == (4, 12, 6)
    assert result["temporal_mask"].shape == (4, 24)
    assert result["channel_mask"].shape == (4, 6)
    context = result["context"]
    temporal_mask = result["temporal_mask"]
    channel_bool_mask = result["channel_mask"]
    assert torch.all(context[temporal_mask] == 0)
    for batch_idx, channel_idx in channel_bool_mask.nonzero(as_tuple=False):
        assert torch.all(context[batch_idx, :, channel_idx] == 0)
