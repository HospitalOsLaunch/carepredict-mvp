"""Anti-collapse probes for TS-JEPA embeddings."""

from __future__ import annotations

import torch
from torch import Tensor


def embedding_std(z: Tensor) -> float:
    """Return mean feature standard deviation over flattened batch and tokens."""
    if z.ndim != 3:
        raise ValueError("expected embedding shape (B, n, D)")
    flat = z.reshape(-1, z.shape[-1]).float()
    return float(flat.std(dim=0, unbiased=False).mean().item())


def mean_offdiag_corr(z: Tensor) -> float:
    """Return mean absolute off-diagonal correlation over embedding dimensions."""
    if z.ndim != 3:
        raise ValueError("expected embedding shape (B, n, D)")
    flat = z.reshape(-1, z.shape[-1]).float()
    centered = flat - flat.mean(dim=0, keepdim=True)
    if centered.shape[-1] < 2:
        return 0.0
    denom = max(centered.shape[0] - 1, 1)
    cov = centered.T @ centered / denom
    std = centered.std(dim=0, unbiased=True)
    corr = cov / (std[:, None] * std[None, :] + 1e-8)
    offdiag_mask = ~torch.eye(corr.shape[0], dtype=torch.bool, device=corr.device)
    mean_corr = corr.abs()[offdiag_mask].mean().clamp(min=0.0, max=1.0)
    return float(mean_corr.item())


offdiag_cov_ratio = mean_offdiag_corr
