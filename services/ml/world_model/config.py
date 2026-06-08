"""Typed configuration for the Hospital World Model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RSSMConfig:
    """Architecture configuration for the recurrent state-space model."""

    obs_dim: int = 1
    action_dim: int = 5
    deter_dim: int = 64
    stoch_dim: int = 32
    hidden_dim: int = 128
    min_std: float = 0.1
    free_bits: float = 1.0
    kl_balance: float = 0.8


@dataclass(frozen=True)
class TrainConfig:
    """Training hyperparameters for the Hospital World Model."""

    lr: float = 3e-4
    grad_clip: float = 100.0
    kl_weight: float = 1.0
    reward_weight: float = 1.0
    imagination_horizon: int = 24
    batch_size: int = 64
    seed: int = 42


@dataclass(frozen=True)
class ServingConfig:
    """Serving-time artifact and forecast configuration."""

    checkpoint_path: str = "artifacts/rssm_checkpoint.pt"
    scaler_path: str = "artifacts/siips_scaler.npz"
    calibration_residuals_path: str = "artifacts/conformal_residuals.npz"
    critical_quantile: float = 0.95
    conformal_alpha: float = 0.1
    max_history_length: int = 720
    max_horizon: int = 168


@dataclass(frozen=True)
class RewardConfig:
    """Reward shaping thresholds expressed in denormalized SIIPS units."""

    p75: float
    p90: float
    moderate_penalty: float = -1.0
    acute_penalty: float = -5.0
