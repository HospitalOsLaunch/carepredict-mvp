"""DreamerV3-style RSSM dynamics over frozen TS-JEPA embeddings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import lightning as L
import torch
import torch.nn.functional as F
from torch import Tensor, nn
from torch.optim import AdamW


@dataclass
class RSSMConfig:
    """Configuration for JEPA-conditioned RSSM dynamics."""

    emb_dim: int = 256
    deter: int = 512
    stoch_cat: int = 32
    stoch_classes: int = 32
    hidden: int = 512
    kl_alpha: float = 0.8
    free_nats: float = 1.0
    unimix: float = 0.01
    lr: float = 3e-4
    grad_clip: float = 1000.0
    siips_weight: float = 1.0
    forecast_horizon: int = 48
    forecast_weight: float = 1.0


def symlog(x: Tensor) -> Tensor:
    """Apply the Dreamer symlog transform."""
    return torch.sign(x) * torch.log1p(torch.abs(x))


def symexp(y: Tensor) -> Tensor:
    """Apply the inverse Dreamer symlog transform."""
    return torch.sign(y) * (torch.exp(torch.abs(y)) - 1.0)


def calendar_encoding(hour_of_day: Tensor, day_of_week: Tensor) -> Tensor:
    """Return deterministic sine/cosine calendar features for origin timestamps."""
    hour = hour_of_day.to(dtype=torch.float32)
    day = day_of_week.to(device=hour.device, dtype=torch.float32)
    two_pi = torch.tensor(2.0 * torch.pi, device=hour.device, dtype=torch.float32)
    hour_angle = two_pi * hour / 24.0
    day_angle = two_pi * day / 7.0
    return torch.stack(
        [
            torch.sin(hour_angle),
            torch.cos(hour_angle),
            torch.sin(day_angle),
            torch.cos(day_angle),
        ],
        dim=-1,
    )


class JepaRSSM(L.LightningModule):
    """RSSM trained on frozen JEPA embeddings with categorical stochastic state."""

    def __init__(self, cfg: RSSMConfig, frozen_encoder: nn.Module, patcher: nn.Module) -> None:
        super().__init__()
        self.cfg = cfg
        self.frozen_encoder = frozen_encoder.eval()
        self.patcher = patcher.eval()
        self.frozen_encoder.requires_grad_(False)
        self.patcher.requires_grad_(False)

        stoch_dim = cfg.stoch_cat * cfg.stoch_classes
        self.input_proj = nn.Linear(cfg.emb_dim + stoch_dim, cfg.hidden)
        self.gru = nn.GRUCell(cfg.hidden, cfg.deter)
        self.prior_head = self._mlp(cfg.deter, cfg.hidden, cfg.stoch_cat * cfg.stoch_classes)
        self.posterior_head = self._mlp(
            cfg.deter + cfg.emb_dim,
            cfg.hidden,
            cfg.stoch_cat * cfg.stoch_classes,
        )
        self.latent_decoder = self._mlp(cfg.deter + stoch_dim, cfg.hidden, cfg.emb_dim)
        self.siips_head = self._mlp(cfg.deter + stoch_dim, cfg.hidden, 1)
        self.forecast_head = self._mlp(
            cfg.deter + stoch_dim + 2,
            cfg.hidden,
            cfg.forecast_horizon,
        )

    def training_step(self, batch: dict[str, Tensor], batch_idx: int) -> Tensor:
        """Compute RSSM reconstruction, KL, and optional SIIPS losses."""
        del batch_idx
        if "series" not in batch:
            raise KeyError("batch must contain a 'series' tensor")
        series = batch["series"].float()
        with torch.no_grad():
            z = self.encode_series(series)
        states = self.unroll(z)
        recon = self.reconstruction_loss(states["features"], z)
        kl = self.balanced_kl(states["post_logits"], states["prior_logits"])
        siips_loss = self.siips_loss(states["features"], batch.get("siips"))
        forecast_loss = self.forecast_loss(
            states["features"],
            batch.get("siips"),
            batch.get("calendar"),
        )
        loss = (
            recon
            + kl
            + self.cfg.siips_weight * siips_loss
            + self.cfg.forecast_weight * forecast_loss
        )
        self.log("rssm/recon", recon, on_step=True, on_epoch=True)
        self.log("rssm/kl", kl, on_step=True, on_epoch=True)
        self.log("rssm/siips", siips_loss, on_step=True, on_epoch=True)
        self.log("rssm/forecast", forecast_loss, on_step=True, on_epoch=True)
        self.log("rssm/loss", loss, on_step=True, on_epoch=True)
        return loss

    @torch.no_grad()
    def predict_siips(self, series: Tensor) -> Tensor:
        """Infer positive-scale SIIPS predictions from a series."""
        z = self.encode_series(series.float())
        states = self.unroll(z)
        out = self.siips_head(states["features"]).squeeze(-1)
        return symexp(out)

    def encode_series(self, series: Tensor) -> Tensor:
        """Encode raw series into frozen JEPA patch embeddings."""
        tokens = self.patcher(series)
        pos_idx = torch.arange(tokens.shape[1], device=tokens.device, dtype=torch.long)
        return self.frozen_encoder(tokens, pos_idx)

    def unroll(self, z: Tensor) -> dict[str, Tensor]:
        """Unroll posterior RSSM states over JEPA embeddings."""
        batch, steps, _ = z.shape
        device = z.device
        dtype = z.dtype
        h = torch.zeros(batch, self.cfg.deter, device=device, dtype=dtype)
        s = torch.zeros(
            batch,
            self.cfg.stoch_cat * self.cfg.stoch_classes,
            device=device,
            dtype=dtype,
        )
        features: list[Tensor] = []
        prior_logits: list[Tensor] = []
        post_logits: list[Tensor] = []
        for step in range(steps):
            cell_input = torch.cat([s, z[:, step]], dim=-1)
            h = self.gru(self.input_proj(cell_input), h)
            prior = self.prior_head(h).reshape(
                batch,
                self.cfg.stoch_cat,
                self.cfg.stoch_classes,
            )
            posterior = self.posterior_head(torch.cat([h, z[:, step]], dim=-1)).reshape(
                batch,
                self.cfg.stoch_cat,
                self.cfg.stoch_classes,
            )
            s = self.sample_stoch(posterior)
            features.append(torch.cat([h, s], dim=-1))
            prior_logits.append(prior)
            post_logits.append(posterior)
        return {
            "features": torch.stack(features, dim=1),
            "prior_logits": torch.stack(prior_logits, dim=1),
            "post_logits": torch.stack(post_logits, dim=1),
        }

    def sample_stoch(self, logits: Tensor) -> Tensor:
        """Sample straight-through one-hot categorical stochastic state."""
        probs = self._unimix_probs(logits)
        flat_probs = probs.reshape(-1, self.cfg.stoch_classes)
        sample_idx = torch.multinomial(flat_probs, num_samples=1).squeeze(-1)
        sample = F.one_hot(sample_idx, self.cfg.stoch_classes).to(dtype=probs.dtype)
        sample = sample.reshape_as(probs)
        straight_through = sample + probs - probs.detach()
        return straight_through.reshape(logits.shape[0], -1)

    def balanced_kl(self, post_logits: Tensor, prior_logits: Tensor) -> Tensor:
        """Return DreamerV3-balanced categorical KL with free-nats floor."""
        post_probs = self._unimix_probs(post_logits)
        prior_probs = self._unimix_probs(prior_logits)
        kl_post_sg = self._categorical_kl(post_probs.detach(), prior_probs)
        kl_prior_sg = self._categorical_kl(post_probs, prior_probs.detach())
        kl = self.cfg.kl_alpha * kl_post_sg + (1.0 - self.cfg.kl_alpha) * kl_prior_sg
        free = torch.full_like(kl, self.cfg.free_nats)
        return torch.maximum(kl, free).mean()

    def reconstruction_loss(self, features: Tensor, z: Tensor) -> Tensor:
        """Predict next JEPA embedding from the current RSSM state."""
        if z.shape[1] < 2:
            return torch.zeros((), device=z.device, dtype=z.dtype)
        pred = self.latent_decoder(features[:, :-1])
        return F.smooth_l1_loss(pred, z[:, 1:])

    def siips_loss(self, features: Tensor, siips: Tensor | None) -> Tensor:
        """Predict symlog SIIPS values when targets are provided."""
        if siips is None:
            return torch.zeros((), device=features.device, dtype=features.dtype)
        target = symlog(siips.to(device=features.device, dtype=features.dtype))
        pred = self.siips_head(features).squeeze(-1)
        horizon = min(pred.shape[1], target.shape[1])
        return F.smooth_l1_loss(pred[:, :horizon], target[:, :horizon])

    def forecast(self, states: dict[str, Any], cal: Tensor) -> Tensor:
        """Return direct multi-horizon symlog SIIPS forecasts for valid posterior origins."""
        features = states["features"]
        origin_slice = self._forecast_origin_slice(int(features.shape[1]))
        if origin_slice.stop <= origin_slice.start:
            return torch.empty(
                features.shape[0],
                0,
                self.cfg.forecast_horizon,
                device=features.device,
                dtype=features.dtype,
            )
        calendar = self._prepare_calendar(cal, features)[:, origin_slice, :]
        head_input = torch.cat([features[:, origin_slice, :], calendar], dim=-1)
        return self.forecast_head(head_input)

    def forecast_loss(self, features: Tensor, siips: Tensor | None, cal: Tensor | None) -> Tensor:
        """Predict the next 48 hourly SIIPS values from daily posterior states."""
        if siips is None:
            return torch.zeros((), device=features.device, dtype=features.dtype)
        target = symlog(siips.to(device=features.device, dtype=features.dtype))
        if target.ndim != 2:
            raise ValueError("siips must have shape [batch, time]")
        horizon = self.cfg.forecast_horizon
        if horizon != 48:
            raise ValueError("daily-patch forecast head expects forecast_horizon=48")
        steps = int(features.shape[1])
        required_hours = steps * 24
        if target.shape[1] < required_hours:
            if cal is None:
                return torch.zeros((), device=features.device, dtype=features.dtype)
            raise ValueError("siips target must contain complete 24h blocks for every daily state")
        origin_slice = self._forecast_origin_slice(steps)
        if origin_slice.stop <= origin_slice.start:
            return torch.zeros((), device=features.device, dtype=features.dtype)
        states = {"features": features}
        calendar = cal if cal is not None else self._zero_calendar(features)
        pred = self.forecast(states, calendar)
        windows = [
            target[:, (origin + 1) * 24 : (origin + 3) * 24]
            for origin in range(origin_slice.start, origin_slice.stop)
        ]
        target_windows = torch.stack(windows, dim=1)
        return F.smooth_l1_loss(pred, target_windows)

    def _prepare_calendar(self, cal: Tensor, features: Tensor) -> Tensor:
        """Return day-of-week encodings for each daily RSSM feature step."""
        calendar = cal.to(device=features.device, dtype=features.dtype)
        if calendar.ndim == 2:
            if calendar.shape[1] not in {2, 4}:
                raise ValueError("cal must have 2 day features or 4 hour/day features")
            daily = calendar[:, -2:][:, None, :].expand(-1, features.shape[1], -1)
            return daily.contiguous()
        valid_shape = (
            calendar.ndim == 3
            and calendar.shape[0] == features.shape[0]
            and calendar.shape[2] in {2, 4}
        )
        if not valid_shape:
            raise ValueError("cal must have shape [batch, 2|4] or [batch, time, 2|4]")
        if calendar.shape[1] >= features.shape[1] * 24:
            indices = torch.arange(
                features.shape[1],
                device=features.device,
                dtype=torch.long,
            )
            indices = torch.clamp((indices + 1) * 24, max=calendar.shape[1] - 1)
            calendar = calendar.index_select(dim=1, index=indices)
        elif calendar.shape[1] < features.shape[1]:
            raise ValueError("cal time dimension must cover all daily RSSM feature steps")
        else:
            calendar = calendar[:, : features.shape[1], :]
        return calendar[:, :, -2:]

    def _zero_calendar(self, features: Tensor) -> Tensor:
        """Return neutral day-of-week encodings for backward-compatible batches."""
        return torch.zeros(
            features.shape[0],
            features.shape[1],
            2,
            device=features.device,
            dtype=features.dtype,
        )

    def _forecast_origin_slice(self, steps: int) -> slice:
        """Return day-boundary origins with two observed days and two target days."""
        return slice(1, max(1, steps - 2))

    def configure_optimizers(self) -> AdamW:
        """Configure AdamW; Trainer owns gradient clipping via grad_clip config."""
        return AdamW(self.parameters(), lr=self.cfg.lr)

    @staticmethod
    def _mlp(in_dim: int, hidden: int, out_dim: int) -> nn.Sequential:
        """Build a two-layer MLP with SiLU nonlinearity."""
        return nn.Sequential(
            nn.Linear(in_dim, hidden),
            nn.SiLU(),
            nn.Linear(hidden, out_dim),
        )

    def _unimix_probs(self, logits: Tensor) -> Tensor:
        """Return unimix-smoothed categorical probabilities."""
        probs = torch.softmax(logits, dim=-1)
        return (1.0 - self.cfg.unimix) * probs + self.cfg.unimix / self.cfg.stoch_classes

    @staticmethod
    def _categorical_kl(p: Tensor, q: Tensor) -> Tensor:
        """Return KL(P || Q), summed over classes and categories."""
        eps = torch.finfo(p.dtype).eps
        kl_per_class = p * (torch.log(p.clamp_min(eps)) - torch.log(q.clamp_min(eps)))
        return kl_per_class.sum(dim=-1).sum(dim=-1)
