from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import torch

from rs_jepa.config import (
    RSJEPAConfig,
    SplitConfig,
    Stage1Config,
    Stage2Config,
    SyntheticConfig,
    TrainingConfig,
)
from rs_jepa.encoder import ObservableEncoder
from rs_jepa.heads import CriticalityReadout, coral_loss, per_site_zscore
from rs_jepa.train import run_stage1_training
from rs_jepa.train_stage2 import freeze_encoder, run_stage2_training

pytestmark = pytest.mark.rs_jepa


def tiny_cfg(checkpoint_path: str = "") -> RSJEPAConfig:
    return RSJEPAConfig(
        seed=17,
        stage1=Stage1Config(
            latent_dim=12,
            encoder_model_dim=12,
            encoder_depth=1,
            encoder_heads=2,
            encoder_ff_dim=24,
            encoder_dropout=0.0,
            encoder_max_steps=96,
            rssm_deter_dim=16,
            rssm_stoch_dim=6,
            predictor_hidden_dim=24,
            predictor_depth=1,
            context_steps=24,
            horizons=(6,),
            batch_size=4,
            ema_ramp_steps=20,
            block_mask_min_frac=0.15,
            block_mask_max_frac=0.30,
            channel_mask_prob=0.20,
        ),
        stage2=Stage2Config(
            k_levels=4,
            head_hidden_dim=16,
            head_depth=2,
            max_epochs=1,
            batch_size=64,
            freeze_backbone=True,
            siips_calibration_enabled=False,
        ),
        split=SplitConfig(temporal_holdout_weeks=1, cross_site_val_fraction=0.33, seed=17),
        synthetic=SyntheticConfig(n_sites=6, total_days=28, seed=17),
        training=TrainingConfig(
            max_epochs=1,
            steps_per_epoch=2,
            probe_every_epochs=1,
            early_collapse_rank_threshold=1.0,
            probe_rank_threshold=4.0,
            probe_stride=24,
            probe_max_samples=200,
            checkpoint_path=checkpoint_path,
        ),
    )


def _ordered_logits(level: int, k_levels: int, magnitude: float = 8.0) -> torch.Tensor:
    values = [magnitude if level > threshold else -magnitude for threshold in range(k_levels - 1)]
    return torch.tensor([values], dtype=torch.float32)


def test_stage2_freeze_blocks_encoder_grads_while_heads_receive_grads() -> None:
    cfg = tiny_cfg()
    encoder = ObservableEncoder(n_obs=9, n_static=4, cfg=cfg.stage1)
    freeze_encoder(encoder)
    heads = CriticalityReadout(cfg.stage1.latent_dim, cfg.stage2)
    x = torch.randn(3, 12, 9)
    static = torch.randn(3, 4)
    levels = torch.randint(0, cfg.stage2.k_levels, (3 * 12,))
    tension_target = torch.rand(3 * 12)

    # No manual detach: the architecture freezes Stage 1 before the backward pass.
    latents = encoder(x, static).reshape(-1, cfg.stage1.latent_dim)
    out = heads(latents)
    loss = coral_loss(out["ordinal_logits"], levels, cfg.stage2.k_levels)
    loss = loss + torch.nn.functional.smooth_l1_loss(out["tension"], tension_target)
    loss.backward()  # type: ignore[no-untyped-call]

    assert all(param.grad is None for param in encoder.parameters())
    head_grads = [param.grad for param in heads.parameters() if param.requires_grad]
    assert head_grads
    assert all(grad is not None and torch.isfinite(grad).all() for grad in head_grads)


def test_coral_loss_is_ordered_and_near_zero_for_perfect_prediction() -> None:
    target = torch.tensor([2])
    perfect = coral_loss(_ordered_logits(2, 4), target, 4)
    adjacent = coral_loss(_ordered_logits(1, 4), target, 4)
    far = coral_loss(_ordered_logits(0, 4), target, 4)
    reversed_far = coral_loss(_ordered_logits(3, 4, magnitude=-8.0), target, 4)
    assert perfect.item() < 1e-3
    assert perfect < adjacent < far
    assert reversed_far > adjacent


def test_head_a_per_site_normalization_uses_local_history_not_global_pool() -> None:
    scores = np.array([0.0, 1.0, 2.0, 10.0, 11.0, 12.0])
    site_ids = np.array(["a", "a", "a", "b", "b", "b"])
    normalized = per_site_zscore(scores, site_ids)
    assert np.allclose(normalized[:3], normalized[3:], atol=1e-6)
    assert abs(float(normalized[:3].mean())) < 1e-6
    assert abs(float(normalized[3:].mean())) < 1e-6


def test_stage2_heads_shapes_and_siips_head_is_flag_gated() -> None:
    cfg = tiny_cfg()
    heads = CriticalityReadout(cfg.stage1.latent_dim, cfg.stage2)
    latents = torch.randn(7, cfg.stage1.latent_dim)
    out = heads(latents)
    assert out["tension"].shape == (7,)
    assert out["ordinal_logits"].shape == (7, cfg.stage2.k_levels - 1)
    with pytest.raises(RuntimeError, match="désactivée"):
        heads.siips(latents)


def test_stage2_training_runs_end_to_end_with_finite_cross_site_and_temporal_metrics(
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "encoder.pt"
    cfg = tiny_cfg(checkpoint_path=str(checkpoint))
    run_stage1_training(cfg, log=False)
    artifacts = run_stage2_training(checkpoint, cfg, log=False)
    assert artifacts.history
    for metric in artifacts.metrics.values():
        assert np.isfinite(metric.ordinal_accuracy)
        assert np.isfinite(metric.mae_levels)
        assert np.isfinite(metric.ranking_corr)
        assert np.isfinite(metric.tension_corr)
        assert metric.n_eval > 0
