"""Tests for TS-JEPA block masking."""

from __future__ import annotations

import numpy as np
import torch

from hospitalos.encoders.ts_jepa.masking import block_mask


def test_block_mask_disjoint_complete_and_ratio() -> None:
    """Context and target masks are disjoint and cover every patch."""
    torch.manual_seed(0)
    np.random.seed(0)
    ctx, tgt = block_mask(32, 0.75, 4, torch.Generator().manual_seed(0))
    assert set(ctx.tolist()).isdisjoint(set(tgt.tolist()))
    assert sorted(ctx.tolist() + tgt.tolist()) == list(range(32))
    assert abs((len(tgt) / 32) - 0.75) <= 0.1


def test_block_mask_seed_reproducibility() -> None:
    """Identical generator seeds produce identical masks."""
    torch.manual_seed(0)
    np.random.seed(0)
    first = block_mask(32, 0.75, 4, torch.Generator().manual_seed(7))
    second = block_mask(32, 0.75, 4, torch.Generator().manual_seed(7))
    assert torch.equal(first[0], second[0])
    assert torch.equal(first[1], second[1])


def test_block_mask_different_seed_changes_mask() -> None:
    """Different seeds produce different target placements."""
    torch.manual_seed(0)
    np.random.seed(0)
    first = block_mask(32, 0.75, 4, torch.Generator().manual_seed(7))
    second = block_mask(32, 0.75, 4, torch.Generator().manual_seed(8))
    assert not torch.equal(first[1], second[1])
