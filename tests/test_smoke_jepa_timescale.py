"""Tests for the Timescale JEPA smoke CLI configuration."""

from __future__ import annotations

import numpy as np
import torch

from hospitalos.encoders.ts_jepa.config import JEPAConfig
from hospitalos.encoders.ts_jepa.jepa_module import JEPALightningModule
from hospitalos.training.smoke_jepa_timescale import parse_args


def test_patch_len_default_preserves_existing_behavior() -> None:
    """The Timescale smoke CLI keeps the historical 24h patch default."""
    args = parse_args([])

    assert args.patch_len == 24


def test_patch_len_one_produces_hourly_patches_for_168h_window() -> None:
    """A 168h Timescale window becomes 168 JEPA states when patch_len=1."""
    torch.manual_seed(0)
    np.random.seed(0)
    channels = 7
    cfg = JEPAConfig(
        in_channels=channels,
        patch_len=1,
        emb_dim=32,
        ctx_layers=1,
        pred_layers=1,
        n_heads=4,
    )
    model = JEPALightningModule(cfg)
    series = torch.randn(1, 168, channels, dtype=torch.float32)

    tokens = model.patcher(series)

    assert tokens.shape == (1, 168, 32)


def test_patcher_input_dimension_is_channels_times_patch_len() -> None:
    """Patchifier projection width follows channels * patch_len for both modes."""
    channels = 7

    default_model = JEPALightningModule(JEPAConfig(in_channels=channels, patch_len=24))
    hourly_model = JEPALightningModule(JEPAConfig(in_channels=channels, patch_len=1))

    assert default_model.patcher.proj.weight.shape == (256, channels * 24)
    assert hourly_model.patcher.proj.weight.shape == (256, channels)
