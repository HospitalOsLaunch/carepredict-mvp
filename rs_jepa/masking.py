"""Composable Stage 1 masks for RS-JEPA."""

from __future__ import annotations

import torch

from rs_jepa.config import Stage1Config


def _rng(generator: torch.Generator | None) -> torch.Generator | None:
    return generator


def forecasting_mask(
    window_steps: int,
    cfg: Stage1Config,
    *,
    horizon: int | None = None,
    generator: torch.Generator | None = None,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Return context indices [0:C] and target indices [C:C+H]."""

    if horizon is None:
        choices = torch.tensor(cfg.horizons, dtype=torch.long)
        pick = int(torch.randint(len(choices), (1,), generator=_rng(generator)).item())
        horizon = int(choices[pick].item())
    if horizon not in cfg.horizons:
        raise ValueError(f"Horizon {horizon} absent de cfg.horizons={cfg.horizons}.")
    context_steps = int(cfg.context_steps)
    if window_steps < context_steps + horizon:
        raise ValueError(
            "Fenêtre trop courte: "
            f"{window_steps} < context_steps+horizon={context_steps + horizon}."
        )
    context_idx = torch.arange(0, context_steps, dtype=torch.long)
    target_idx = torch.arange(context_steps, context_steps + horizon, dtype=torch.long)
    return context_idx, target_idx


def split_forecasting_window(
    x: torch.Tensor,
    cfg: Stage1Config,
    *,
    horizon: int | None = None,
    generator: torch.Generator | None = None,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    context_idx, target_idx = forecasting_mask(
        x.shape[1], cfg, horizon=horizon, generator=generator
    )
    return x[:, context_idx], x[:, target_idx], context_idx, target_idx


def block_temporal_mask(
    context: torch.Tensor,
    cfg: Stage1Config,
    *,
    generator: torch.Generator | None = None,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Zero one contiguous temporal span per sample inside the context."""

    if context.ndim != 3:
        raise ValueError("context doit avoir la forme [B, C, n_obs].")
    batch, steps, _channels = context.shape
    min_len = max(1, int(round(cfg.block_mask_min_frac * steps)))
    max_len = max(min_len, int(round(cfg.block_mask_max_frac * steps)))
    masked = context.clone()
    mask = torch.zeros(batch, steps, dtype=torch.bool, device=context.device)
    for b_idx in range(batch):
        span_draw = torch.randint(
            min_len,
            max_len + 1,
            (1,),
            generator=_rng(generator),
            device="cpu",
        )
        span_len = int(span_draw.item())
        start_draw = torch.randint(
            0,
            steps - span_len + 1,
            (1,),
            generator=_rng(generator),
            device="cpu",
        )
        start = int(start_draw.item())
        mask[b_idx, start : start + span_len] = True
    masked[mask] = 0
    return masked, mask


def channel_mask(
    x: torch.Tensor,
    cfg: Stage1Config,
    *,
    generator: torch.Generator | None = None,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Zero entire channels for each sample."""

    if x.ndim != 3:
        raise ValueError("x doit avoir la forme [B, T, n_obs].")
    batch, _steps, channels = x.shape
    draws = torch.rand(batch, channels, generator=_rng(generator), device=x.device)
    mask = draws < cfg.channel_mask_prob
    masked = x.clone()
    masked = masked.masked_fill(mask[:, None, :], 0)
    return masked, mask


def apply_stage1_masks(
    x: torch.Tensor,
    cfg: Stage1Config,
    *,
    horizon: int | None = None,
    generator: torch.Generator | None = None,
) -> dict[str, torch.Tensor]:
    """Apply forecasting split, block-temporal mask, and channel mask to a batch."""

    context, target, context_idx, target_idx = split_forecasting_window(
        x, cfg, horizon=horizon, generator=generator
    )
    context, temporal_mask = block_temporal_mask(context, cfg, generator=generator)
    context, channel_bool_mask = channel_mask(context, cfg, generator=generator)
    return {
        "context": context,
        "target": target,
        "context_idx": context_idx,
        "target_idx": target_idx,
        "temporal_mask": temporal_mask,
        "channel_mask": channel_bool_mask,
    }
