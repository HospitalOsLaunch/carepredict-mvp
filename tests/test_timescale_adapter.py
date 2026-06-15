"""Tests for the canonical TimescaleDB hospital adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import numpy as np
import pytest
import torch

from data.synthetic.siips_generator import db_config_from_env
from hospitalos.data.timescale_adapter import (
    CHANNEL_NAMES,
    TimescaleDatasetConfig,
    build_timescale_dataset,
)


@pytest.fixture(scope="module")
def db_overrides() -> dict[str, Any]:
    """Return DB overrides or skip cleanly when TimescaleDB is unavailable."""
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
    return {"connect_timeout": 1}


@pytest.fixture(scope="module")
def train_dataset(db_overrides: dict[str, Any]):
    """Build a deterministic train split for one service."""
    return build_timescale_dataset(
        TimescaleDatasetConfig(
            window_days=7,
            split="train",
            train_end="2025-07-01",
            services=["urg-001"],
            db_overrides=db_overrides,
        )
    )


def test_timescale_adapter_shapes_dtypes_and_channels(train_dataset) -> None:
    """Adapter returns the exact JEPA/RSSM tensor contract."""
    torch.manual_seed(0)
    np.random.seed(0)
    item = train_dataset[0]
    assert train_dataset.channel_names == CHANNEL_NAMES
    assert item["series"].shape == (7 * 24, 7)
    assert item["siips"].shape == (7 * 24,)
    assert item["series"].dtype == torch.float32
    assert item["siips"].dtype == torch.float32
    assert item["series"].shape[0] % 24 == 0


def test_timescale_adapter_target_not_leaked_into_series(train_dataset) -> None:
    """SIIPS target is positive and not exactly duplicated by any feature channel."""
    torch.manual_seed(0)
    np.random.seed(0)
    items = [train_dataset[index] for index in range(min(len(train_dataset), 8))]
    siips = np.concatenate([item["siips"].numpy() for item in items])
    series = np.concatenate([item["series"].numpy() for item in items], axis=0)
    assert np.all(siips > 0.0)
    correlations: list[float] = []
    for column in range(series.shape[1]):
        if np.std(series[:, column]) == 0.0 or np.std(siips) == 0.0:
            correlations.append(0.0)
        else:
            corr = float(np.corrcoef(siips, series[:, column])[0, 1])
            correlations.append(abs(corr))
    assert max(correlations) < 0.999


def test_timescale_adapter_split_boundaries(db_overrides: dict[str, Any]) -> None:
    """Train and val windows respect train_end and never straddle the boundary."""
    torch.manual_seed(0)
    np.random.seed(0)
    train = build_timescale_dataset(
        TimescaleDatasetConfig(
            split="train",
            train_end="2025-07-01",
            services=["urg-001"],
            db_overrides=db_overrides,
        )
    )
    val = build_timescale_dataset(
        TimescaleDatasetConfig(
            split="val",
            train_end="2025-07-01",
            services=["urg-001"],
            db_overrides=db_overrides,
        )
    )
    boundary = datetime(2025, 7, 1, tzinfo=UTC)
    assert all(end <= boundary for end in train.window_ends)
    assert all(start >= boundary for start in val.window_starts)


def test_timescale_adapter_determinism(db_overrides: dict[str, Any]) -> None:
    """Same config yields identical first window tensors."""
    torch.manual_seed(0)
    np.random.seed(0)
    cfg = TimescaleDatasetConfig(
        split="train",
        train_end="2025-07-01",
        services=["urg-001"],
        db_overrides=db_overrides,
    )
    first = build_timescale_dataset(cfg)[0]
    second = build_timescale_dataset(cfg)[0]
    assert torch.equal(first["series"], second["series"])
    assert torch.equal(first["siips"], second["siips"])


def test_timescale_adapter_rejected_window_counter(train_dataset) -> None:
    """Rejected window count is exposed as a non-negative integer."""
    assert isinstance(train_dataset.n_rejected_windows, int)
    assert train_dataset.n_rejected_windows >= 0
