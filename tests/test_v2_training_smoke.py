"""Smoke tests for v2 direct forecast-head training."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import torch

from data.synthetic.siips_generator import db_config_from_env
from hospitalos.encoders.ts_jepa.encoder import TransformerEncoder
from hospitalos.encoders.ts_jepa.patcher import Patchifier
from hospitalos.training.train_v2_forecast import main, split_train_calibration_indices


def test_split_train_calibration_indices_excludes_calibration_tail() -> None:
    """The last 10% by date is reserved for calibration and excluded from training."""
    starts = [datetime(2025, 1, 1, tzinfo=UTC) + timedelta(days=7 * index) for index in range(20)]

    train_indices, calibration_indices = split_train_calibration_indices(starts, cal_frac=0.1)

    assert set(train_indices).isdisjoint(calibration_indices)
    assert len(calibration_indices) == 2
    latest_train = max(starts[index] for index in train_indices)
    earliest_calibration = min(starts[index] for index in calibration_indices)
    assert latest_train < earliest_calibration


@pytest.fixture(scope="module")
def db_available() -> None:
    """Skip DB-backed smoke tests cleanly when TimescaleDB is unavailable."""
    try:
        import psycopg2
    except ImportError as exc:
        pytest.skip(f"psycopg2 unavailable: {exc}")
    config = db_config_from_env()
    config["connect_timeout"] = 1
    try:
        with psycopg2.connect(**config) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"TimescaleDB unavailable: {exc}")


def test_v2_training_smoke_50_steps(tmp_path: Path, db_available: None) -> None:
    """Train v2 for 50 steps and persist all forecast artifacts."""
    del db_available
    encoder_ckpt = tmp_path / "daily_encoder.pt"
    write_daily_encoder_checkpoint(encoder_ckpt, in_channels=7, emb_dim=32)
    out_dir = tmp_path / "v2_forecast"

    summary = main(
        [
            "--steps",
            "50",
            "--train-end",
            "2025-07-01",
            "--services",
            "urg-001",
            "--encoder-ckpt",
            str(encoder_ckpt),
            "--out",
            str(out_dir),
            "--seed",
            "0",
        ]
    )

    assert (out_dir / "checkpoint.pt").exists()
    assert (out_dir / "conformal_q.npz").exists()
    assert (out_dir / "train_config.json").exists()
    assert summary["n_train_windows"] > 0
    assert summary["n_calibration_windows"] > 0


def write_daily_encoder_checkpoint(path: Path, *, in_channels: int, emb_dim: int) -> None:
    """Write a minimal daily JEPA encoder checkpoint compatible with the trainer."""
    torch.manual_seed(0)
    patcher = Patchifier(in_channels=in_channels, patch_len=24, emb_dim=emb_dim)
    encoder = TransformerEncoder(emb_dim=emb_dim, depth=1, n_heads=8)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "patcher": patcher.state_dict(),
            "context_encoder": encoder.state_dict(),
        },
        path,
    )
