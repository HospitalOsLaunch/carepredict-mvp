"""Smoke tests for the synthetic RSSM training script."""

from __future__ import annotations

import math
from pathlib import Path

import torch

from scripts.train_rssm_synthetic import main, parse_args


def test_train_rssm_synthetic_smoke(tmp_path: Path) -> None:
    """Run a tiny CPU training job and verify all serving artifacts."""
    args = parse_args(
        [
            "--months",
            "1",
            "--steps",
            "10",
            "--batch-size",
            "4",
            "--horizon",
            "6",
            "--history-length",
            "12",
            "--output-dir",
            str(tmp_path),
            "--device",
            "cpu",
            "--log-every",
            "0",
        ]
    )
    history = main(args)
    checkpoint_path = tmp_path / "rssm_checkpoint.pt"
    scaler_path = tmp_path / "siips_scaler.npz"
    residual_path = tmp_path / "conformal_residuals.npz"

    assert checkpoint_path.exists()
    assert scaler_path.exists()
    assert residual_path.exists()

    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    expected_keys = {
        "model_state_dict",
        "rssm_config",
        "config",
        "train_config",
        "reward_config",
        "step",
        "siips_mean",
        "siips_std",
        "p75",
        "p90",
    }
    assert expected_keys.issubset(checkpoint.keys())
    assert history
    for record in history:
        for value in record.values():
            assert math.isfinite(float(value))
