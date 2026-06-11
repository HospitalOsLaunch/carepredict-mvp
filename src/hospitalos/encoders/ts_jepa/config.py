"""Configuration dataclass for TS-JEPA pretraining."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class JEPAConfig:
    """Hyperparameters for the time-series JEPA encoder."""

    in_channels: int
    patch_len: int = 24
    stride: int = 24
    emb_dim: int = 256
    ctx_layers: int = 8
    pred_layers: int = 4
    pred_dim: int = 192
    n_heads: int = 8
    mlp_ratio: int = 4
    mask_ratio: float = 0.75
    n_target_blocks: int = 4
    ema_start: float = 0.996
    ema_end: float = 1.0
    lr: float = 1.5e-4
    wd: float = 0.04
    warmup_frac: float = 0.1
    max_steps: int = 100_000
    probe_every_n_steps: int = 200
