"""Tests for synthetic generator adapter."""

from __future__ import annotations

import numpy as np
import torch

from hospitalos.data.synthetic_adapter import SyntheticDatasetConfig, build_synthetic_dataset


def test_synthetic_adapter_shapes_and_dtypes() -> None:
    """Adapter returns float32 windows with aligned SIIPS targets."""
    torch.manual_seed(0)
    np.random.seed(0)
    dataset = build_synthetic_dataset(SyntheticDatasetConfig(n_days=14, window_days=7, seed=0))
    item = dataset[0]
    assert item["series"].shape == (7 * 24, len(dataset.channels))
    assert item["siips"].shape == (7 * 24,)
    assert item["series"].dtype == torch.float32
    assert item["siips"].dtype == torch.float32
    assert item["series"].shape[0] % 24 == 0


def test_synthetic_adapter_determinism() -> None:
    """Same seed returns identical tensors, different seed changes them."""
    torch.manual_seed(0)
    np.random.seed(0)
    first = build_synthetic_dataset(SyntheticDatasetConfig(n_days=14, window_days=7, seed=0))[0]
    second = build_synthetic_dataset(SyntheticDatasetConfig(n_days=14, window_days=7, seed=0))[0]
    third = build_synthetic_dataset(SyntheticDatasetConfig(n_days=14, window_days=7, seed=1))[0]
    assert torch.equal(first["series"], second["series"])
    assert torch.equal(first["siips"], second["siips"])
    assert not torch.equal(first["series"], third["series"])


def test_synthetic_adapter_sanity() -> None:
    """Adapter tensors are finite, active, and non-negative where required."""
    torch.manual_seed(0)
    np.random.seed(0)
    item = build_synthetic_dataset(SyntheticDatasetConfig(n_days=14, window_days=7, seed=0))[0]
    assert torch.isfinite(item["series"]).all()
    assert torch.isfinite(item["siips"]).all()
    assert torch.all(item["series"].std(dim=0) > 0)
    assert torch.all(item["siips"] >= 0)


def test_synthetic_adapter_non_overlapping_window_count() -> None:
    """Dataset length follows D4 temporal split window counts."""
    torch.manual_seed(0)
    np.random.seed(0)
    train_cfg = SyntheticDatasetConfig(n_days=21, window_days=7, seed=0)
    train_dataset = build_synthetic_dataset(train_cfg)
    expected_train = int(
        np.floor((train_cfg.n_days * (1.0 - train_cfg.val_frac)) / train_cfg.window_days)
    )
    assert len(train_dataset) == expected_train

    val_cfg = SyntheticDatasetConfig(n_days=21, window_days=7, seed=0, split="val")
    val_dataset = build_synthetic_dataset(val_cfg)
    expected_val = int(np.floor((val_cfg.n_days * val_cfg.val_frac) / val_cfg.window_days))
    assert len(val_dataset) == expected_val
