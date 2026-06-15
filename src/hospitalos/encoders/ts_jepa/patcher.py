"""Patchification and stateless instance normalization for TS-JEPA."""

from __future__ import annotations

from torch import Tensor, nn


def instance_normalize(x: Tensor) -> Tensor:
    """Normalize each sample and channel across time without stored state."""
    if x.ndim != 3:
        raise ValueError("expected input shape (B, T, C)")
    mean = x.mean(dim=1, keepdim=True)
    std = x.std(dim=1, keepdim=True, unbiased=False)
    return (x - mean) / (std + 1e-5)


class Patchifier(nn.Module):
    """Convert normalized time-series windows into patch embeddings."""

    def __init__(self, in_channels: int, patch_len: int = 24, emb_dim: int = 256) -> None:
        super().__init__()
        self.in_channels = in_channels
        self.patch_len = patch_len
        self.emb_dim = emb_dim
        self.proj = nn.Linear(patch_len * in_channels, emb_dim)

    def n_patches(self, t: int) -> int:
        """Return the number of non-overlapping patches for a length ``t``."""
        if t % self.patch_len != 0:
            raise AssertionError("T must be divisible by patch_len")
        return t // self.patch_len

    def forward(self, x: Tensor) -> Tensor:
        """Return patch embeddings with shape ``(B, N, emb_dim)``."""
        if x.ndim != 3:
            raise ValueError("expected input shape (B, T, C)")
        batch, time, channels = x.shape
        if channels != self.in_channels:
            raise ValueError("input channel count does not match Patchifier")
        n = self.n_patches(time)
        x_norm = instance_normalize(x)
        patches = x_norm.reshape(batch, n, self.patch_len * channels)
        return self.proj(patches)
