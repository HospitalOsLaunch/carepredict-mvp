from __future__ import annotations

import pandas as pd
import pytest

from rs_jepa.config import load_config
from rs_jepa.seed import set_global_seed
from rs_jepa.splits import (
    CROSS_SITE_VAL,
    TEMPORAL_VAL,
    TRAIN,
    add_validation_splits,
    require_monotonic_by_site,
)

pytestmark = pytest.mark.rs_jepa


def test_phase_a_config_loads_expected_horizons():
    cfg = load_config("configs/phaseA.yaml")
    assert cfg.stage1.horizons == (6, 24, 72, 168)
    assert cfg.stage1.context_steps == 168
    assert cfg.stage2.k_levels == 4


def test_split_is_cross_site_and_temporal():
    rows = []
    for site in ["a", "b", "c", "d", "e"]:
        for ts in pd.date_range("2024-01-01", periods=24 * 30, freq="h"):
            rows.append({"site_id": site, "timestamp": ts})
    frame = pd.DataFrame(rows)
    cfg = load_config("configs/phaseA.yaml").split
    split_frame, summary = add_validation_splits(frame, cfg)
    assert set(summary.train_sites).isdisjoint(summary.cross_site_val_sites)
    cross_site_sites = set(split_frame.loc[split_frame["split"] == CROSS_SITE_VAL, "site_id"])
    assert cross_site_sites == set(summary.cross_site_val_sites)
    train_ts = split_frame.loc[split_frame["split"] == TRAIN, "timestamp"]
    temporal_val_ts = split_frame.loc[split_frame["split"] == TEMPORAL_VAL, "timestamp"]
    assert (train_ts < summary.temporal_holdout_start).all()
    assert (temporal_val_ts >= summary.temporal_holdout_start).all()


def test_split_guard_rejects_shuffled_site_history():
    frame = pd.DataFrame(
        {
            "site_id": ["a", "a", "a"],
            "timestamp": pd.to_datetime(["2024-01-02", "2024-01-01", "2024-01-03"]),
        }
    )
    with pytest.raises(ValueError, match="Split aléatoire refusé"):
        require_monotonic_by_site(frame)


def test_global_seed_reproducible_for_torch_and_numpy():
    import numpy as np
    import torch

    set_global_seed(123)
    a_np = np.random.normal(size=3)
    a_torch = torch.randn(3)
    set_global_seed(123)
    b_np = np.random.normal(size=3)
    b_torch = torch.randn(3)
    assert np.allclose(a_np, b_np)
    assert torch.allclose(a_torch, b_torch)
