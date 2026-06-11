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


def offdiag_cov_ratio(z: Tensor) -> float:
    """Return off-diagonal absolute covariance mass divided by diagonal mass."""
    if z.ndim != 3:
        raise ValueError("expected embedding shape (B, n, D)")
    flat = z.reshape(-1, z.shape[-1]).float()
    centered = flat - flat.mean(dim=0, keepdim=True)
    denom = max(centered.shape[0] - 1, 1)
    cov = centered.T @ centered / denom
    diag_abs = torch.diagonal(cov).abs().sum()
    offdiag_abs = cov.abs().sum() - diag_abs
    if float(diag_abs.item()) == 0.0:
        return 0.0
    return float((offdiag_abs / diag_abs).item())
