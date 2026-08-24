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


class ActionDeltaHead(nn.Module):
    """Interventional readout: true criticality delta from paired rollout latents."""

    def __init__(self, latent_dim: int, cfg: Stage2Config, *, n_channels: int = 2) -> None:
        super().__init__()
        self.n_channels = int(n_channels)
        self.channel_embed = nn.Embedding(self.n_channels, 4)
        input_dim = latent_dim * 3 + 4
        self.net = _mlp(input_dim, cfg.head_hidden_dim, 1, cfg.head_depth, cfg.dropout)

    def forward(
        self,
        z0: torch.Tensor,
        z_action: torch.Tensor,
        channel_id: torch.Tensor | int,
    ) -> torch.Tensor:
        if z0.shape != z_action.shape:
            raise ValueError("z0 et z_action doivent avoir la même forme.")
        if z0.ndim != 3:
            raise ValueError("z0 et z_action doivent avoir la forme [B, H, Z].")
        batch, horizon, _latent = z0.shape
        if isinstance(channel_id, int):
            channels = torch.full(
                (batch, horizon),
                int(channel_id),
                dtype=torch.long,
                device=z0.device,
            )
        else:
            channels = channel_id.to(device=z0.device, dtype=torch.long)
            if channels.ndim == 0:
                channels = channels.expand(batch, horizon)
            elif channels.ndim == 1:
                channels = channels[:, None].expand(batch, horizon)
        if channels.shape != (batch, horizon):
            raise ValueError(
                f"channel_id doit être scalaire, [B], ou [B,H], reçu={tuple(channels.shape)}."
            )
        channel_features = self.channel_embed(channels)
        features = torch.cat([z0, z_action, z_action - z0, channel_features], dim=-1)
        return self.net(features).squeeze(-1)


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
