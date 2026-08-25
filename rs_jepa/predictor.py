"""Latent predictor head for RS-JEPA target rollout states."""

from __future__ import annotations

from typing import cast

import torch
from torch import Tensor, nn

from rs_jepa.config import Stage1Config


class LatentPredictor(nn.Module):
    """Map RSSM states [B, H, state_dim] to target latents [B, H, Z]."""

    def __init__(self, cfg: Stage1Config) -> None:
        super().__init__()
        state_dim = int(cfg.rssm_deter_dim + cfg.rssm_stoch_dim)
        hidden_dim = int(cfg.predictor_hidden_dim)
        depth = max(1, int(cfg.predictor_depth))
        layers: list[nn.Module] = [
            nn.LayerNorm(state_dim),
            nn.Linear(state_dim, hidden_dim),
            nn.GELU(),
        ]
        for _idx in range(depth - 1):
            layers.extend([nn.Linear(hidden_dim, hidden_dim), nn.GELU()])
        layers.append(nn.Linear(hidden_dim, cfg.latent_dim))
        self.net = nn.Sequential(*layers)

    def forward(self, states: torch.Tensor) -> torch.Tensor:
        if states.ndim != 3:
            raise ValueError("states doit avoir la forme [B, H, state_dim].")
        return cast(Tensor, self.net(states))
