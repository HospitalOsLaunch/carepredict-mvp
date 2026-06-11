"""Tests for TS-JEPA anti-collapse probes."""

from __future__ import annotations

import numpy as np
import torch

from hospitalos.encoders.ts_jepa.probes import embedding_std, mean_offdiag_corr


def test_embedding_std_constant_is_zero() -> None:
    """Constant embeddings have near-zero feature standard deviation."""
    torch.manual_seed(0)
    np.random.seed(0)
    z = torch.ones(2, 4, 8, dtype=torch.float32)
    assert embedding_std(z) == 0.0


def test_embedding_std_random_is_near_one() -> None:
    """Random normal embeddings have feature standard deviation near one."""
    torch.manual_seed(0)
    np.random.seed(0)
    z = torch.randn(128, 16, 8, dtype=torch.float32)
    assert abs(embedding_std(z) - 1.0) <= 0.1


def test_mean_offdiag_corr_independent_small() -> None:
    """Independent dimensions have low mean off-diagonal correlation."""
    torch.manual_seed(0)
    np.random.seed(0)
    z = torch.randn(256, 16, 16, dtype=torch.float32)
    assert mean_offdiag_corr(z) < 0.1


def test_mean_offdiag_corr_duplicated_large() -> None:
    """Duplicated dimensions have high mean off-diagonal correlation."""
    torch.manual_seed(0)
    np.random.seed(0)
    base = torch.randn(256, 16, 1, dtype=torch.float32)
    z = base.repeat(1, 1, 16)
    assert mean_offdiag_corr(z) > 0.9
