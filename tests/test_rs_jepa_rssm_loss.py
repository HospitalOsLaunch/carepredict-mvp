from __future__ import annotations

from dataclasses import replace

import pytest
import torch

from rs_jepa.config import Stage1Config
from rs_jepa.diagnostics_latent import effective_rank, latent_batch_stats
from rs_jepa.ema import EMATargetEncoder
from rs_jepa.encoder import ObservableEncoder
from rs_jepa.loss import covariance_loss, latent_jepa_loss, variance_loss
from rs_jepa.predictor import LatentPredictor
from rs_jepa.rssm import RSSM

pytestmark = pytest.mark.rs_jepa


def tiny_cfg(**kwargs) -> Stage1Config:
    cfg = Stage1Config(
        latent_dim=16,
        encoder_model_dim=16,
        encoder_depth=1,
        encoder_heads=2,
        encoder_ff_dim=32,
        encoder_dropout=0.0,
        encoder_max_steps=128,
        rssm_deter_dim=24,
        rssm_stoch_dim=8,
        predictor_hidden_dim=32,
        predictor_depth=2,
        context_steps=12,
        horizons=(4, 8),
    )
    return replace(cfg, **kwargs)


def finite_grad_sum(module: torch.nn.Module) -> float:
    total = 0.0
    for param in module.parameters():
        if param.grad is not None:
            assert torch.isfinite(param.grad).all()
            total += float(param.grad.abs().sum().item())
    return total


def test_rssm_rollout_shapes_prior_only_target():
    torch.manual_seed(0)
    cfg = tiny_cfg()
    rssm = RSSM(cfg, n_static=3)
    z_context = torch.randn(5, 12, cfg.latent_dim)
    static = torch.randn(5, 3)
    out = rssm.rollout(z_context, horizon=8, static=static)
    assert out.states.shape == (5, 8, cfg.rssm_deter_dim + cfg.rssm_stoch_dim)
    assert out.prior_mean.shape == (5, 8, cfg.rssm_stoch_dim)
    assert out.prior_std.shape == (5, 8, cfg.rssm_stoch_dim)
    assert torch.all(out.prior_std > cfg.rssm_min_std)


def test_static_covariates_change_rssm_rollout():
    torch.manual_seed(0)
    cfg = tiny_cfg()
    rssm = RSSM(cfg, n_static=2)
    z_context = torch.randn(3, 12, cfg.latent_dim)
    zero_static = torch.zeros(3, 2)
    shifted_static = torch.ones(3, 2)
    first = rssm.rollout(z_context, horizon=4, static=zero_static).states
    second = rssm.rollout(z_context, horizon=4, static=shifted_static).states
    assert not torch.allclose(first, second)


def test_rssm_is_deterministic_under_fixed_seed():
    cfg = tiny_cfg()
    z_context = torch.randn(2, 12, cfg.latent_dim)
    static = torch.randn(2, 2)
    torch.manual_seed(123)
    first = RSSM(cfg, n_static=2)
    first_out = first.rollout(z_context, horizon=4, static=static).states
    torch.manual_seed(123)
    second = RSSM(cfg, n_static=2)
    second_out = second.rollout(z_context, horizon=4, static=static).states
    assert torch.allclose(first_out, second_out)


def test_predictor_output_shape_matches_target_encoder_latents():
    torch.manual_seed(0)
    cfg = tiny_cfg()
    encoder = ObservableEncoder(n_obs=6, n_static=2, cfg=cfg)
    target = EMATargetEncoder(encoder)
    rssm = RSSM(cfg, n_static=2)
    predictor = LatentPredictor(cfg)
    x_context = torch.randn(4, 12, 6)
    x_target = torch.randn(4, 8, 6)
    static = torch.randn(4, 2)
    z_context = encoder(x_context, static)
    states = rssm.rollout(z_context, horizon=8, static=static).states
    pred = predictor(states)
    target_latents = target(x_target, static)
    assert pred.shape == target_latents.shape


def test_latent_jepa_loss_backward_grads_are_finite():
    torch.manual_seed(0)
    cfg = tiny_cfg()
    encoder = ObservableEncoder(n_obs=5, n_static=2, cfg=cfg)
    target = EMATargetEncoder(encoder)
    rssm = RSSM(cfg, n_static=2)
    predictor = LatentPredictor(cfg)
    x_context = torch.randn(3, 12, 5)
    x_target = torch.randn(3, 4, 5)
    static = torch.randn(3, 2)

    pred = predictor(rssm.rollout(encoder(x_context, static), horizon=4, static=static).states)
    target_latents = target(x_target, static)
    loss, components = latent_jepa_loss(pred, target_latents, cfg)
    assert torch.isfinite(loss)
    assert set(components) == {"total", "pred", "var", "cov"}
    loss.backward()
    assert finite_grad_sum(encoder) > 0
    assert finite_grad_sum(rssm) > 0
    assert finite_grad_sum(predictor) > 0


def test_joint_graph_stop_gradient_blocks_ema_target_branch():
    torch.manual_seed(0)
    cfg = tiny_cfg()
    online_encoder = ObservableEncoder(n_obs=5, n_static=2, cfg=cfg)
    ema_target = EMATargetEncoder(online_encoder)
    rssm = RSSM(cfg, n_static=2)
    predictor = LatentPredictor(cfg)
    x_context = torch.randn(4, 12, 5)
    x_target = torch.randn(4, 8, 5)
    static = torch.randn(4, 2)

    z_context = online_encoder(x_context, static)
    rollout_states = rssm.rollout(z_context, horizon=8, static=static).states
    pred_latents = predictor(rollout_states)
    target_latents = ema_target(x_target, static)
    loss, _components = latent_jepa_loss(pred_latents, target_latents, cfg)
    loss.backward()

    target_grads_none = all(param.grad is None for param in ema_target.target.parameters())
    online_grad = finite_grad_sum(online_encoder)
    rssm_grad = finite_grad_sum(rssm)
    predictor_grad = finite_grad_sum(predictor)
    print(
        "joint-stop-grad "
        f"target_grads_none={target_grads_none} "
        f"online_grad={online_grad:.6f} rssm_grad={rssm_grad:.6f} "
        f"predictor_grad={predictor_grad:.6f}"
    )
    assert target_grads_none
    assert online_grad > 0
    assert rssm_grad > 0
    assert predictor_grad > 0


def test_vicreg_variance_penalizes_collapsed_latents_more_than_spread_latents():
    collapsed = torch.zeros(8, 6, 16)
    spread = torch.randn(8, 6, 16) * 2.0
    assert variance_loss(collapsed) > 0.9
    assert variance_loss(spread) < variance_loss(collapsed)


def test_covariance_loss_finite():
    latents = torch.randn(8, 6, 16)
    loss = covariance_loss(latents)
    assert torch.isfinite(loss)
    assert loss >= 0


def test_effective_rank_detects_collapsed_vs_spread_latents():
    collapsed = torch.ones(16, 8, 12)
    spread = torch.randn(16, 8, 12)
    collapsed_rank = effective_rank(collapsed)
    spread_rank = effective_rank(spread)
    assert collapsed_rank < 1.1
    assert spread_rank > collapsed_rank
    stats = latent_batch_stats(spread)
    assert set(stats) == {"effective_rank", "per_dim_std_min", "per_dim_std_mean"}
    assert stats["effective_rank"] > 1.0
    assert stats["per_dim_std_mean"] > 0.0
