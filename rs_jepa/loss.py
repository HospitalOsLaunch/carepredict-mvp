"""Latent JEPA loss with VICReg collapse guards."""

from __future__ import annotations

import torch
from torch.nn import functional as F

from rs_jepa.config import Stage1Config


def variance_loss(
    latents: torch.Tensor,
    target_std: float = 1.0,
    eps: float = 1e-4,
) -> torch.Tensor:
    flat = latents.reshape(-1, latents.shape[-1])
    std = torch.sqrt(flat.var(dim=0, unbiased=False) + eps)
    return torch.relu(target_std - std).mean()


def covariance_loss(latents: torch.Tensor) -> torch.Tensor:
    flat = latents.reshape(-1, latents.shape[-1])
    flat = flat - flat.mean(dim=0, keepdim=True)
    denom = max(flat.shape[0] - 1, 1)
    cov = (flat.T @ flat) / denom
    off_diag = cov - torch.diag(torch.diag(cov))
    return off_diag.pow(2).sum() / latents.shape[-1]


def latent_jepa_loss(
    pred_latents: torch.Tensor,
    target_latents: torch.Tensor,
    cfg: Stage1Config,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    """Compute latent-only JEPA loss; target branch is detached here by design."""

    if pred_latents.shape != target_latents.shape:
        raise ValueError(
            f"pred_latents et target_latents doivent matcher: "
            f"{tuple(pred_latents.shape)} != {tuple(target_latents.shape)}."
        )
    target = target_latents.detach()
    pred = F.smooth_l1_loss(pred_latents, target)
    var = variance_loss(pred_latents)
    cov = covariance_loss(pred_latents)
    total = cfg.w_pred * pred + cfg.w_var * var + cfg.w_cov * cov
    return total, {
        "total": total.detach(),
        "pred": pred.detach(),
        "var": var.detach(),
        "cov": cov.detach(),
    }
