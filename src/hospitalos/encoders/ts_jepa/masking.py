"""Contiguous block masking for TS-JEPA."""

from __future__ import annotations

import torch
from torch import Tensor


def block_mask(
    n_patches: int,
    mask_ratio: float,
    n_target_blocks: int,
    generator: torch.Generator,
) -> tuple[Tensor, Tensor]:
    """Return sorted context and target indices from random contiguous blocks."""
    if n_patches <= 1:
        raise AssertionError("n_patches must be greater than one")
    k = round(mask_ratio * n_patches)
    if k <= 0 or k >= n_patches:
        raise AssertionError("target count must leave non-empty context")
    if n_target_blocks <= 0 or n_target_blocks > k:
        raise AssertionError("n_target_blocks must be in [1, target_count]")

    base = k // n_target_blocks
    rem = k % n_target_blocks
    lengths = [base + (1 if idx < rem else 0) for idx in range(n_target_blocks)]
    if any(length <= 0 or length > n_patches for length in lengths):
        raise AssertionError("infeasible target block lengths")

    intervals: list[tuple[int, int]] = []
    max_restarts = 512
    max_attempts = 256
    for _restart in range(max_restarts):
        intervals.clear()
        success = True
        for length in lengths:
            placed = False
            for _attempt in range(max_attempts):
                start = int(torch.randint(0, n_patches - length + 1, (1,), generator=generator))
                end = start + length
                if all(end <= old_start or start >= old_end for old_start, old_end in intervals):
                    intervals.append((start, end))
                    placed = True
                    break
            if not placed:
                success = False
                break
        if success:
            target = sorted(
                patch_idx for start, end in intervals for patch_idx in range(start, end)
            )
            target_set = set(target)
            context = [idx for idx in range(n_patches) if idx not in target_set]
            return torch.tensor(context, dtype=torch.long), torch.tensor(target, dtype=torch.long)

    raise AssertionError("could not place non-overlapping target blocks")
