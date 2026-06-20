"""Dreamer-style recurrent state-space dynamics for RS-JEPA Stage 1."""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import nn
from torch.nn import functional as F

from rs_jepa.config import Stage1Config


@dataclass(frozen=True)
class RSSMOutput:
    states: torch.Tensor
    prior_mean: torch.Tensor
    prior_std: torch.Tensor


class RSSM(nn.Module):
    """RSSM with posterior context updates and prior-only target rollout."""

    def __init__(self, cfg: Stage1Config, n_static: int = 0) -> None:
        super().__init__()
        self.latent_dim = int(cfg.latent_dim)
        self.deter_dim = int(cfg.rssm_deter_dim)
        self.stoch_dim = int(cfg.rssm_stoch_dim)
        self.state_dim = self.deter_dim + self.stoch_dim
        self.min_std = float(cfg.rssm_min_std)
        self.n_static = int(n_static)
        self.static_to_h = nn.Linear(self.n_static, self.deter_dim) if self.n_static > 0 else None
        self.gru = nn.GRUCell(self.latent_dim + self.stoch_dim, self.deter_dim)
        self.prior = nn.Linear(self.deter_dim, 2 * self.stoch_dim)
        self.posterior = nn.Linear(self.deter_dim + self.latent_dim, 2 * self.stoch_dim)
        self.state_norm = nn.LayerNorm(self.state_dim) if cfg.rssm_layer_norm else nn.Identity()

    def initial_state(
        self,
        batch_size: int,
        static: torch.Tensor | None,
        device: torch.device,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        if self.static_to_h is not None:
            if static is None:
                static = torch.zeros(batch_size, self.n_static, device=device)
            if static.ndim != 2 or static.shape != (batch_size, self.n_static):
                raise ValueError(
                    f"static doit avoir la forme [{batch_size}, {self.n_static}], "
                    f"reçu={tuple(static.shape)}."
                )
            h = torch.tanh(self.static_to_h(static.to(device=device)))
        else:
            h = torch.zeros(batch_size, self.deter_dim, device=device)
        s = torch.zeros(batch_size, self.stoch_dim, device=device)
        return h, s

    def _stats(self, layer: nn.Linear, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        mean, raw_std = layer(x).chunk(2, dim=-1)
        std = F.softplus(raw_std) + self.min_std
        return mean, std

    def _state(self, h: torch.Tensor, s: torch.Tensor) -> torch.Tensor:
        return self.state_norm(torch.cat([h, s], dim=-1))

    def observe_context(
        self,
        z_context: torch.Tensor,
        static: torch.Tensor | None = None,
    ) -> torch.Tensor:
        if z_context.ndim != 3 or z_context.shape[-1] != self.latent_dim:
            raise ValueError("z_context doit avoir la forme [B, C, latent_dim].")
        batch_size, context_steps, _ = z_context.shape
        h, s = self.initial_state(batch_size, static, z_context.device)
        states = []
        for step in range(context_steps):
            z_t = z_context[:, step]
            h = self.gru(torch.cat([z_t, s], dim=-1), h)
            post_mean, _post_std = self._stats(self.posterior, torch.cat([h, z_t], dim=-1))
            s = post_mean
            states.append(self._state(h, s))
        return torch.stack(states, dim=1)

    def rollout(
        self,
        z_context: torch.Tensor,
        horizon: int,
        static: torch.Tensor | None = None,
    ) -> RSSMOutput:
        """Roll target states with the prior only; target observations are not read."""

        if horizon <= 0:
            raise ValueError("horizon doit être positif.")
        if z_context.ndim != 3 or z_context.shape[-1] != self.latent_dim:
            raise ValueError("z_context doit avoir la forme [B, C, latent_dim].")
        batch_size, context_steps, _ = z_context.shape
        h, s = self.initial_state(batch_size, static, z_context.device)
        for step in range(context_steps):
            z_t = z_context[:, step]
            h = self.gru(torch.cat([z_t, s], dim=-1), h)
            post_mean, _post_std = self._stats(self.posterior, torch.cat([h, z_t], dim=-1))
            s = post_mean

        zero_z = torch.zeros(
            batch_size,
            self.latent_dim,
            device=z_context.device,
            dtype=z_context.dtype,
        )
        states = []
        prior_means = []
        prior_stds = []
        for _step in range(horizon):
            h = self.gru(torch.cat([zero_z, s], dim=-1), h)
            prior_mean, prior_std = self._stats(self.prior, h)
            s = prior_mean
            states.append(self._state(h, s))
            prior_means.append(prior_mean)
            prior_stds.append(prior_std)
        return RSSMOutput(
            states=torch.stack(states, dim=1),
            prior_mean=torch.stack(prior_means, dim=1),
            prior_std=torch.stack(prior_stds, dim=1),
        )
