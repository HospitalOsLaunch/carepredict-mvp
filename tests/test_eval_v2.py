"""Unit tests for v2 frozen-protocol evaluation helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import numpy as np
import torch
from torch import nn

from hospitalos.eval.eval_v2 import (
    V2Artifacts,
    V2Record,
    eval_history_length,
    history_frame,
    metric_block,
    validate_critical_checks,
)


def test_metric_block_uses_raw_space_interval_formula() -> None:
    """Coverage and width are computed from raw lower/upper bounds."""
    records = [
        V2Record(
            origin=datetime(2025, 7, 2, tzinfo=UTC),
            horizon=24,
            y_true=110.0,
            y_pred=100.0,
            lower=90.0,
            upper=120.0,
        ),
        V2Record(
            origin=datetime(2025, 7, 3, tzinfo=UTC),
            horizon=24,
            y_true=150.0,
            y_pred=100.0,
            lower=90.0,
            upper=120.0,
        ),
    ]

    metrics = metric_block(records, seed=0)

    assert metrics["mae"] == 30.0
    assert metrics["coverage90"] == 0.5
    assert metrics["mean_interval_width"] == 30.0
    assert metrics["n_samples"] == 2


def test_history_frame_returns_complete_7_channel_window() -> None:
    """Feature history uses full Timescale channel vectors, not SIIPS-only input."""
    origin = datetime(2025, 7, 8, tzinfo=UTC)
    start = origin - timedelta(hours=167)
    rows = {
        start + timedelta(hours=offset): np.full(7, float(offset), dtype=np.float32)
        for offset in range(168)
    }

    history = history_frame(rows, origin=origin, length=168)

    assert history is not None
    assert history.shape == (1, 168, 7)
    assert history.dtype == torch.float32


def test_history_frame_returns_none_for_missing_hour() -> None:
    """Incomplete feature histories are skipped by the evaluator."""
    origin = datetime(2025, 7, 8, tzinfo=UTC)
    start = origin - timedelta(hours=167)
    rows = {
        start + timedelta(hours=offset): np.full(7, 1.0, dtype=np.float32) for offset in range(167)
    }

    assert history_frame(rows, origin=origin, length=168) is None


def test_validate_critical_checks_accepts_f2_artifact_metadata() -> None:
    """Critical checks enforce patch length, git hash, and conformal shapes."""
    artifacts = V2Artifacts(
        model=None,  # type: ignore[arg-type]
        train_config={"encoder": {"patch_len": 1}, "git_hash": "abc"},
        q90_lo=np.zeros(48, dtype=np.float64),
        q90_hi=np.zeros(48, dtype=np.float64),
        artifact_paths={"checkpoint": Path("checkpoint.pt")},
    )

    validate_critical_checks(artifacts=artifacts, expected_git_hash="abc")


def test_eval_history_length_matches_training_origin_range() -> None:
    """Daily eval history extracts d=4, the last supervised training origin."""
    artifacts = V2Artifacts(
        model=cast(
            nn.Module,
            type("Model", (), {"cfg": type("Cfg", (), {"forecast_horizon": 48})()})(),
        ),
        train_config={"encoder": {"patch_len": 24}, "git_hash": "abc"},
        q90_lo=np.zeros(48, dtype=np.float64),
        q90_hi=np.zeros(48, dtype=np.float64),
        artifact_paths={"checkpoint": Path("checkpoint.pt")},
    )

    assert eval_history_length(artifacts) == 120
