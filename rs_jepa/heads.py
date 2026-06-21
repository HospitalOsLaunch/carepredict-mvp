"""Criticality readout heads for frozen RS-JEPA latents."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from rs_jepa.config import Stage2Config


def _mlp(
    input_dim: int,
    hidden_dim: int,
    output_dim: int,
    depth: int,
    dropout: float,
) -> nn.Sequential:
    layers: list[nn.Module] = []
    width = input_dim
    for _ in range(max(1, depth) - 1):
        layers.append(nn.Linear(width, hidden_dim))
        layers.append(nn.GELU())
        if dropout > 0:
            layers.append(nn.Dropout(dropout))
        width = hidden_dim
    layers.append(nn.Linear(width, output_dim))
    return nn.Sequential(*layers)


class TensionHead(nn.Module):
    """Head A: continuous unitless tension score from frozen latents."""

    def __init__(self, latent_dim: int, cfg: Stage2Config) -> None:
        super().__init__()
        self.net = _mlp(latent_dim, cfg.head_hidden_dim, 1, cfg.head_depth, cfg.dropout)

    def forward(self, latents: torch.Tensor) -> torch.Tensor:
        return self.net(latents).squeeze(-1)


class OrdinalCriticalityHead(nn.Module):
    """Head B: CORAL-style ordinal criticality logits."""

    def __init__(self, latent_dim: int, cfg: Stage2Config) -> None:
        super().__init__()
        if cfg.k_levels < 2:
            raise ValueError("k_levels doit être >= 2 pour une tête ordinale.")
        self.k_levels = int(cfg.k_levels)
        self.net = _mlp(
            latent_dim,
            cfg.head_hidden_dim,
            self.k_levels - 1,
            cfg.head_depth,
            cfg.dropout,
        )

    def forward(self, latents: torch.Tensor) -> torch.Tensor:
        return self.net(latents)


class LocalSIIPSCalibrationHead(nn.Module):
    """Head C scaffold: local SIIPS calibration, disabled unless labels exist."""

    def __init__(self, latent_dim: int, cfg: Stage2Config) -> None:
        super().__init__()
        self.enabled = bool(cfg.siips_calibration_enabled)
        self.net = _mlp(latent_dim, cfg.head_hidden_dim, 1, cfg.head_depth, cfg.dropout)
        if not self.enabled:
            for param in self.net.parameters():
                param.requires_grad_(False)

    def forward(self, latents: torch.Tensor) -> torch.Tensor:
        if not self.enabled:
            raise RuntimeError("La calibration SIIPS locale est désactivée pour Phase A.")
        return self.net(latents).squeeze(-1)


class CriticalityReadout(nn.Module):
    """Heads A/B plus optional local calibration head C."""

    def __init__(self, latent_dim: int, cfg: Stage2Config) -> None:
        super().__init__()
        self.tension = TensionHead(latent_dim, cfg)
        self.ordinal = OrdinalCriticalityHead(latent_dim, cfg)
        self.siips = LocalSIIPSCalibrationHead(latent_dim, cfg)

    def forward(self, latents: torch.Tensor) -> dict[str, torch.Tensor]:
        return {
            "tension": self.tension(latents),
            "ordinal_logits": self.ordinal(latents),
        }


def coral_targets(levels: torch.Tensor, k_levels: int) -> torch.Tensor:
    """Encode levels as cumulative binary labels y > threshold_k."""

    if levels.ndim != 1:
        raise ValueError("levels doit être un vecteur [N].")
    thresholds = torch.arange(k_levels - 1, device=levels.device)
    return (levels.long().unsqueeze(1) > thresholds.unsqueeze(0)).to(dtype=torch.float32)


def coral_loss(logits: torch.Tensor, levels: torch.Tensor, k_levels: int) -> torch.Tensor:
    """CORAL ordinal BCE loss; farther ordinal mistakes pay more thresholds."""

    if logits.ndim != 2 or logits.shape[1] != k_levels - 1:
        raise ValueError(f"logits doit être [N, {k_levels - 1}].")
    targets = coral_targets(levels, k_levels)
    return F.binary_cross_entropy_with_logits(logits, targets)


def predict_ordinal_level(logits: torch.Tensor) -> torch.Tensor:
    """Predict ordered level by counting passed cumulative thresholds."""

    return (torch.sigmoid(logits) >= 0.5).sum(dim=1).long()


def ranking_correlation(scores: np.ndarray, targets: np.ndarray) -> float:
    """Pearson correlation between score and target ranking, finite for flat targets."""

    scores = np.asarray(scores, dtype=float)
    targets = np.asarray(targets, dtype=float)
    if scores.size == 0 or np.std(scores) < 1e-12 or np.std(targets) < 1e-12:
        return 0.0
    return float(np.corrcoef(scores, targets)[0, 1])


def per_site_zscore(scores: np.ndarray, site_ids: np.ndarray, eps: float = 1e-8) -> np.ndarray:
    """Normalize Head-A scores within each site history, never globally."""

    scores = np.asarray(scores, dtype=float)
    site_ids = np.asarray(site_ids)
    out = np.empty_like(scores, dtype=float)
    for site_id in np.unique(site_ids):
        mask = site_ids == site_id
        local = scores[mask]
        out[mask] = (local - local.mean()) / (local.std() + eps)
    return out


@dataclass(frozen=True)
class Stage2Metrics:
    split: str
    ordinal_accuracy: float
    mae_levels: float
    ranking_corr: float
    tension_corr: float
    n_eval: int
