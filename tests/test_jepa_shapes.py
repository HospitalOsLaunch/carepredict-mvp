"""Shape and normalization tests for TS-JEPA."""

from __future__ import annotations

import numpy as np
import torch

from hospitalos.encoders.ts_jepa.config import JEPAConfig
from hospitalos.encoders.ts_jepa.jepa_module import JEPALightningModule
from hospitalos.encoders.ts_jepa.masking import block_mask
from hospitalos.encoders.ts_jepa.patcher import Patchifier, instance_normalize


def test_jepa_training_step_returns_finite_scalar_loss() -> None:
    """A small JEPA module returns a finite scalar loss for valid series."""
    torch.manual_seed(0)
    np.random.seed(0)
    cfg = JEPAConfig(
        in_channels=5,
        emb_dim=256,
        ctx_layers=1,
        pred_layers=1,
        n_heads=8,
        n_target_blocks=1,
        probe_every_n_steps=0,
    )
    module = JEPALightningModule(cfg)
    series = torch.randn(2, 96, 5, dtype=torch.float32)
    loss = module.training_step({"series": series}, 0)
    assert loss.shape == torch.Size([])
    assert torch.isfinite(loss)


def test_predictor_output_shape_matches_targets() -> None:
    """Predictor output is ``(B, n_tgt, emb_dim)``."""
    torch.manual_seed(0)
    np.random.seed(0)
    cfg = JEPAConfig(
        in_channels=5,
        emb_dim=256,
        ctx_layers=1,
        pred_layers=1,
        n_heads=8,
        n_target_blocks=1,
    )
    module = JEPALightningModule(cfg)
    series = torch.randn(2, 96, 5, dtype=torch.float32)
    tokens = module.patcher(series)
    ctx_idx, tgt_idx = block_mask(
        tokens.shape[1], cfg.mask_ratio, cfg.n_target_blocks, torch.Generator().manual_seed(0)
    )
    ctx = module.context_encoder(tokens[:, ctx_idx], ctx_idx)
    pred = module.predictor(ctx, ctx_idx, tgt_idx)
    assert pred.shape == (2, len(tgt_idx), 256)


def test_patchifier_instance_normalization_mean_std() -> None:
    """Instance normalization gives per-sample/channel mean zero and std one."""
    torch.manual_seed(0)
    np.random.seed(0)
    x = torch.randn(3, 96, 5, dtype=torch.float32) * 7.0 + 13.0
    normalized = instance_normalize(x)
    assert torch.allclose(normalized.mean(dim=1), torch.zeros(3, 5), atol=1e-5)
    assert torch.allclose(
        normalized.std(dim=1, unbiased=False),
        torch.ones(3, 5),
        atol=1e-4,
    )


def test_patchifier_n_patches_and_forward_shape() -> None:
    """Patchifier reports and returns the expected patch count."""
    torch.manual_seed(0)
    np.random.seed(0)
    patcher = Patchifier(in_channels=5, patch_len=24, emb_dim=256)
    out = patcher(torch.randn(2, 96, 5, dtype=torch.float32))
    assert patcher.n_patches(96) == 4
    assert out.shape == (2, 4, 256)
