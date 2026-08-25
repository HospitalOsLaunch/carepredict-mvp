from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
import torch

from rs_jepa.config import Stage1Config
from rs_jepa.rssm import RSSM, RSSMOutput

pytestmark = pytest.mark.rs_jepa


def tiny_cfg(**kwargs: Any) -> Stage1Config:
    cfg = Stage1Config(
        latent_dim=12,
        rssm_deter_dim=18,
        rssm_stoch_dim=6,
        rssm_min_std=0.1,
        rssm_layer_norm=True,
        action_dim=2,
        context_steps=8,
        horizons=(5,),
    )
    return replace(cfg, **kwargs)


def _legacy_rollout_without_actions(
    rssm: RSSM,
    z_context: torch.Tensor,
    horizon: int,
    static: torch.Tensor | None,
) -> RSSMOutput:
    batch_size, context_steps, _ = z_context.shape
    h, s = rssm.initial_state(batch_size, static, z_context.device)
    for step in range(context_steps):
        z_t = z_context[:, step]
        h = rssm.gru(torch.cat([z_t, s], dim=-1), h)
        post_mean, _post_std = rssm._stats(rssm.posterior, torch.cat([h, z_t], dim=-1))
        s = post_mean

    zero_z = torch.zeros(
        batch_size,
        rssm.latent_dim,
        device=z_context.device,
        dtype=z_context.dtype,
    )
    states = []
    prior_means = []
    prior_stds = []
    for _step in range(horizon):
        h = rssm.gru(torch.cat([zero_z, s], dim=-1), h)
        prior_mean, prior_std = rssm._stats(rssm.prior, h)
        s = prior_mean
        states.append(rssm._state(h, s))
        prior_means.append(prior_mean)
        prior_stds.append(prior_std)
    return RSSMOutput(
        states=torch.stack(states, dim=1),
        prior_mean=torch.stack(prior_means, dim=1),
        prior_std=torch.stack(prior_stds, dim=1),
    )


def test_rssm_accepts_context_and_future_actions_with_expected_shapes() -> None:
    torch.manual_seed(0)
    cfg = tiny_cfg()
    rssm = RSSM(cfg, n_static=3)
    z_context = torch.randn(4, 8, cfg.latent_dim)
    static = torch.randn(4, 3)
    actions_context = torch.randn(4, 8, cfg.action_dim)
    actions_future = torch.randn(4, 5, cfg.action_dim)

    observed = rssm.observe_context(
        z_context,
        actions_context=actions_context,
        static=static,
    )
    rolled = rssm.rollout(
        z_context,
        horizon=5,
        static=static,
        actions_context=actions_context,
        actions_future=actions_future,
    )

    assert observed.shape == (4, 8, cfg.rssm_deter_dim + cfg.rssm_stoch_dim)
    assert rolled.states.shape == (4, 5, cfg.rssm_deter_dim + cfg.rssm_stoch_dim)
    assert rolled.prior_mean.shape == (4, 5, cfg.rssm_stoch_dim)
    assert rolled.prior_std.shape == (4, 5, cfg.rssm_stoch_dim)


def test_different_future_actions_change_rollout_trajectory() -> None:
    torch.manual_seed(1)
    cfg = tiny_cfg()
    rssm = RSSM(cfg, n_static=2)
    z_context = torch.randn(3, 8, cfg.latent_dim)
    static = torch.randn(3, 2)
    actions_context = torch.zeros(3, 8, cfg.action_dim)
    low_action = torch.zeros(3, 5, cfg.action_dim)
    high_action = torch.zeros(3, 5, cfg.action_dim)
    high_action[..., 0] = 0.20
    high_action[..., 1] = 0.05

    low = rssm.rollout(
        z_context,
        horizon=5,
        static=static,
        actions_context=actions_context,
        actions_future=low_action,
    ).states
    high = rssm.rollout(
        z_context,
        horizon=5,
        static=static,
        actions_context=actions_context,
        actions_future=high_action,
    ).states

    assert not torch.allclose(low, high)


def test_no_action_matches_explicit_zero_action_for_action_dim_two() -> None:
    torch.manual_seed(2)
    cfg = tiny_cfg()
    rssm = RSSM(cfg, n_static=1)
    z_context = torch.randn(2, 8, cfg.latent_dim)
    static = torch.randn(2, 1)
    zero_context = torch.zeros(2, 8, cfg.action_dim)
    zero_future = torch.zeros(2, 5, cfg.action_dim)

    implicit = rssm.rollout(z_context, horizon=5, static=static).states
    explicit = rssm.rollout(
        z_context,
        horizon=5,
        static=static,
        actions_context=zero_context,
        actions_future=zero_future,
    ).states

    assert torch.allclose(implicit, explicit)


def test_action_dim_zero_reproduces_legacy_no_action_rollout_seed_fixed() -> None:
    torch.manual_seed(3)
    cfg = tiny_cfg(action_dim=0)
    rssm = RSSM(cfg, n_static=2)
    z_context = torch.randn(2, 8, cfg.latent_dim)
    static = torch.randn(2, 2)

    current = rssm.rollout(z_context, horizon=5, static=static)
    legacy = _legacy_rollout_without_actions(rssm, z_context, horizon=5, static=static)

    assert torch.allclose(current.states, legacy.states)
    assert torch.allclose(current.prior_mean, legacy.prior_mean)
    assert torch.allclose(current.prior_std, legacy.prior_std)


def test_rollout_loss_backpropagates_to_gru_action_weights() -> None:
    torch.manual_seed(4)
    cfg = tiny_cfg()
    rssm = RSSM(cfg, n_static=2)
    z_context = torch.randn(3, 8, cfg.latent_dim)
    static = torch.randn(3, 2)
    actions_context = torch.zeros(3, 8, cfg.action_dim)
    actions_future = torch.randn(3, 5, cfg.action_dim, requires_grad=True)

    states = rssm.rollout(
        z_context,
        horizon=5,
        static=static,
        actions_context=actions_context,
        actions_future=actions_future,
    ).states
    loss = states.square().mean()
    loss.backward()  # type: ignore[no-untyped-call]

    assert actions_future.grad is not None
    assert torch.isfinite(actions_future.grad).all()
    assert float(actions_future.grad.abs().sum()) > 0.0

    grad = rssm.gru.weight_ih.grad
    assert grad is not None
    action_start = cfg.latent_dim + cfg.rssm_stoch_dim
    action_grad = grad[:, action_start:]
    assert torch.isfinite(action_grad).all()
    assert float(action_grad.abs().sum()) > 0.0
