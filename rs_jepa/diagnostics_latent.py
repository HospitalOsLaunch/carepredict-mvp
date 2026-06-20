"""Latent collapse diagnostics for RS-JEPA."""

from __future__ import annotations

import torch


def effective_rank(latents: torch.Tensor, eps: float = 1e-12) -> torch.Tensor:
    """Entropy rank of the latent covariance eigenvalue spectrum."""

    if latents.ndim < 2:
        raise ValueError("latents doit contenir au moins un axe batch et un axe latent.")
    flat = latents.reshape(-1, latents.shape[-1])
    flat = flat - flat.mean(dim=0, keepdim=True)
    denom = max(flat.shape[0] - 1, 1)
    cov = (flat.T @ flat) / denom
    eigvals = torch.linalg.eigvalsh(cov).clamp_min(0)
    spectrum = eigvals / eigvals.sum().clamp_min(eps)
    entropy = -(spectrum * torch.log(spectrum.clamp_min(eps))).sum()
    return torch.exp(entropy)


def latent_batch_stats(latents: torch.Tensor) -> dict[str, float]:
    flat = latents.reshape(-1, latents.shape[-1])
    per_dim_std = flat.std(dim=0, unbiased=False)
    return {
        "effective_rank": float(effective_rank(latents).detach().cpu().item()),
        "per_dim_std_min": float(per_dim_std.min().detach().cpu().item()),
        "per_dim_std_mean": float(per_dim_std.mean().detach().cpu().item()),
    }
