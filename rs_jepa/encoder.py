"""Per-timestep observable encoder for RS-JEPA Stage 1."""

from __future__ import annotations

import math
from collections.abc import Sequence

import torch
from torch import nn

from rs_jepa.config import Stage1Config

FORBIDDEN_ENCODER_INPUT_COLUMNS = {
    "criticality",
    "criticality_level",
    "kappa",
    "acuity",
    "staff_ratio",
    "occupancy",
    "capacity",
    "inflow",
    "discharges",
}


def validate_observable_columns(feature_names: Sequence[str] | None) -> None:
    """Reject hidden labels or absolute simulator internals at the encoder boundary."""

    if feature_names is None:
        return
    forbidden = sorted(set(feature_names) & FORBIDDEN_ENCODER_INPUT_COLUMNS)
    if forbidden:
        raise ValueError(f"Colonnes interdites pour l'encodeur observable: {forbidden}")


class SinusoidalPositionEncoding(nn.Module):
    """Sinusoidal position encoding with a config-defined maximum length."""

    def __init__(self, max_steps: int, model_dim: int) -> None:
        super().__init__()
        position = torch.arange(max_steps, dtype=torch.float32).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, model_dim, 2, dtype=torch.float32) * (-math.log(10_000.0) / model_dim)
        )
        pe = torch.zeros(max_steps, model_dim, dtype=torch.float32)
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term[: pe[:, 1::2].shape[1]])
        self.register_buffer("pe", pe.unsqueeze(0), persistent=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if x.ndim != 3:
            raise ValueError("L'entrée positionnelle doit être [B, T, D].")
        steps = x.shape[1]
        if steps > self.pe.shape[1]:
            raise ValueError(
                f"Fenêtre T={steps} supérieure au maximum configuré {self.pe.shape[1]}."
            )
        return x + self.pe[:, :steps].to(dtype=x.dtype, device=x.device)


class ObservableEncoder(nn.Module):
    """Encode observable channels [B, T, n_obs] into latent states [B, T, Z]."""

    def __init__(
        self,
        n_obs: int,
        n_static: int,
        cfg: Stage1Config,
        feature_names: Sequence[str] | None = None,
    ) -> None:
        super().__init__()
        validate_observable_columns(feature_names)
        if n_obs <= 0:
            raise ValueError("n_obs doit être positif.")
        if n_static < 0:
            raise ValueError("n_static ne peut pas être négatif.")
        if cfg.encoder_model_dim % cfg.encoder_heads != 0:
            raise ValueError("encoder_model_dim doit être divisible par encoder_heads.")
        self.n_obs = int(n_obs)
        self.n_static = int(n_static)
        self.latent_dim = int(cfg.latent_dim)
        self.model_dim = int(cfg.encoder_model_dim)
        self.input_proj = nn.Linear(self.n_obs, self.model_dim)
        self.static_proj = nn.Linear(self.n_static, self.model_dim) if self.n_static > 0 else None
        self.position = SinusoidalPositionEncoding(cfg.encoder_max_steps, self.model_dim)
        layer = nn.TransformerEncoderLayer(
            d_model=self.model_dim,
            nhead=cfg.encoder_heads,
            dim_feedforward=cfg.encoder_ff_dim,
            dropout=cfg.encoder_dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.transformer = nn.TransformerEncoder(layer, num_layers=cfg.encoder_depth)
        self.norm = nn.LayerNorm(self.model_dim)
        self.output_proj = nn.Linear(self.model_dim, self.latent_dim)

    def forward(self, x: torch.Tensor, static: torch.Tensor | None = None) -> torch.Tensor:
        if x.ndim != 3:
            raise ValueError("x doit avoir la forme [B, T, n_obs].")
        if x.shape[-1] != self.n_obs:
            raise ValueError(f"n_obs attendu={self.n_obs}, reçu={x.shape[-1]}.")
        h = self.input_proj(x)
        if self.static_proj is not None:
            if static is None:
                static_embedding = torch.zeros(
                    x.shape[0], self.model_dim, dtype=h.dtype, device=h.device
                )
            else:
                if static.ndim != 2 or static.shape != (x.shape[0], self.n_static):
                    raise ValueError(
                        f"static doit avoir la forme [{x.shape[0]}, {self.n_static}], "
                        f"reçu={tuple(static.shape)}."
                    )
                static_embedding = self.static_proj(static.to(dtype=h.dtype, device=h.device))
            h = h + static_embedding.unsqueeze(1)
        h = self.position(h)
        h = self.transformer(h)
        return self.output_proj(self.norm(h))
