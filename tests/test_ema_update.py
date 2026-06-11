"""Tests for TS-JEPA EMA target updates."""

from __future__ import annotations

import numpy as np
import torch

from hospitalos.encoders.ts_jepa.config import JEPAConfig
from hospitalos.encoders.ts_jepa.jepa_module import JEPALightningModule


def test_ema_update_moves_target_towards_context() -> None:
    """Target parameters move strictly between old target and context values."""
    torch.manual_seed(0)
    np.random.seed(0)
    cfg = JEPAConfig(in_channels=2, emb_dim=32, ctx_layers=1, pred_layers=1, n_heads=4)
    module = JEPALightningModule(cfg)
    target_param = next(module.target_encoder.parameters())
    context_param = next(module.context_encoder.parameters())
    target_param.data.fill_(0.0)
    context_param.data.fill_(1.0)
    module.update_target_encoder()
    assert torch.all(target_param > 0.0)
    assert torch.all(target_param < 1.0)


def test_target_requires_grad_false() -> None:
    """Target encoder parameters are frozen."""
    torch.manual_seed(0)
    np.random.seed(0)
    cfg = JEPAConfig(in_channels=2, emb_dim=32, ctx_layers=1, pred_layers=1, n_heads=4)
    module = JEPALightningModule(cfg)
    assert not any(param.requires_grad for param in module.target_encoder.parameters())


def test_ema_momentum_step_zero_equals_start() -> None:
    """EMA momentum at step zero equals ``ema_start``."""
    torch.manual_seed(0)
    np.random.seed(0)
    cfg = JEPAConfig(in_channels=2, emb_dim=32, ctx_layers=1, pred_layers=1, n_heads=4)
    module = JEPALightningModule(cfg)
    assert abs(module.ema_momentum() - cfg.ema_start) <= 1e-6
