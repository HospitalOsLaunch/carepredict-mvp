"""Integration tests for JEPA-conditioned RSSM dynamics."""

from __future__ import annotations

from typing import cast

import numpy as np
import torch
from torch import Tensor, nn

from hospitalos.dynamics.jepa_rssm import JepaRSSM, RSSMConfig, symexp


class DummyPatcher(nn.Module):
    """Patch raw series by averaging over non-overlapping windows."""

    def __init__(self, patch_len: int = 24) -> None:
        super().__init__()
        self.patch_len = patch_len

    def forward(self, series: Tensor) -> Tensor:
        """Return mean patches with shape ``(B, N, C)``."""
        batch, time, channels = series.shape
        n_patches = time // self.patch_len
        return series.reshape(batch, n_patches, self.patch_len, channels).mean(dim=2)


class DummyEncoder(nn.Module):
    """Identity-like linear encoder accepting JEPA encoder signature."""

    def __init__(self, in_dim: int, emb_dim: int) -> None:
        super().__init__()
        self.proj = nn.Linear(in_dim, emb_dim, bias=False)

    def forward(self, tokens: Tensor, pos_idx: Tensor) -> Tensor:
        """Project tokens and ignore position indices."""
        del pos_idx
        return cast(Tensor, self.proj(tokens))


def test_jepa_rssm_training_step_backward_and_freezing() -> None:
    """RSSM losses are finite, backpropagatable, and keep encoder frozen."""
    torch.manual_seed(0)
    np.random.seed(0)
    cfg = RSSMConfig(emb_dim=8, deter=16, stoch_cat=4, stoch_classes=4, hidden=32)
    encoder = DummyEncoder(in_dim=4, emb_dim=8)
    patcher = DummyPatcher()
    model = JepaRSSM(cfg, encoder, patcher)
    series = torch.randn(2, 48, 4, dtype=torch.float32)
    siips = torch.tensor([[10.0, 12.0], [8.0, 14.0]], dtype=torch.float32)

    loss = model.training_step({"series": series, "siips": siips}, 0)
    assert torch.isfinite(loss)
    loss.backward()  # type: ignore[no-untyped-call]
    assert all(param.grad is None for param in encoder.parameters())
    assert any(param.grad is not None for param in model.gru.parameters())


def test_jepa_rssm_siips_inference_shape_and_symexp_positive() -> None:
    """SIIPS inference returns patch-aligned shape and symexp maps positives positive."""
    torch.manual_seed(0)
    np.random.seed(0)
    cfg = RSSMConfig(emb_dim=8, deter=16, stoch_cat=4, stoch_classes=4, hidden=32)
    model = JepaRSSM(cfg, DummyEncoder(in_dim=4, emb_dim=8), DummyPatcher())
    series = torch.randn(2, 48, 4, dtype=torch.float32)

    out = model.predict_siips(series)
    assert out.shape == (2, 2)
    assert torch.all(symexp(torch.ones_like(out)) > 0.0)
