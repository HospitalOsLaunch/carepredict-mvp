"""Feature loading utilities for model training."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class TrainingSplit:
    """Temporal train/validation/test split."""

    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame


def load_synthetic_training_frame(csv_path: Path | None = None, days: int = 45) -> pd.DataFrame:
    """Load a local synthetic frame or generate a deterministic fallback."""
    if csv_path is not None and csv_path.exists():
        frame = pd.read_csv(csv_path)
        if "measured_at" in frame.columns:
            frame = frame.rename(columns={"measured_at": "timestamp"})
        if "siips_score" not in frame.columns:
            raise ValueError("synthetic CSV must include siips_score")
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        if "service_id" not in frame.columns:
            frame["service_id"] = "urg-001"
        if "hospital_profile" not in frame.columns:
            frame["hospital_profile"] = "acute"
        return frame

    periods = days * 24
    timestamps = pd.date_range("2026-01-01", periods=periods, freq="h", tz="UTC")
    hour = np.arange(periods)
    daily = 8.0 * np.sin((hour % 24) / 24.0 * 2.0 * np.pi)
    weekly = np.where(pd.Series(timestamps).dt.dayofweek.isin([0, 1]), 4.0, 0.0)
    trend = hour * 0.005
    siips = 55.0 + daily + weekly + trend
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "service_id": "urg-001",
            "hospital_profile": "acute",
            "siips_score": siips.astype(float),
            "scheduled_discharges": np.where((hour % 24) == 11, 2, 0),
            "scheduled_surgeries": np.where((hour % 24) == 14, 1, 0),
            "expected_transfers_in": np.where((hour % 24) == 16, 1, 0),
            "expected_transfers_out": np.where((hour % 24) == 10, 1, 0),
            "scheduled_admissions": np.where((hour % 24) == 9, 2, 0),
            "planned_procedures": np.where((hour % 24) == 15, 1, 0),
            "planned_staff_redeployments": np.where((hour % 24) == 7, 1, 0),
        }
    )


def temporal_split(
    frame: pd.DataFrame, train_ratio: float = 0.70, val_ratio: float = 0.15
) -> TrainingSplit:
    """Split a frame in temporal order: 70% train, 15% validation, 15% test."""
    if frame.empty:
        raise ValueError("frame must not be empty")
    if not 0 < train_ratio < 1 or not 0 < val_ratio < 1:
        raise ValueError("split ratios must be in (0, 1)")
    if train_ratio + val_ratio >= 1:
        raise ValueError("train_ratio + val_ratio must be below 1")

    ordered = frame.sort_values("timestamp").reset_index(drop=True)
    train_end = int(len(ordered) * train_ratio)
    val_end = int(len(ordered) * (train_ratio + val_ratio))
    return TrainingSplit(
        train=ordered.iloc[:train_end].reset_index(drop=True),
        validation=ordered.iloc[train_end:val_end].reset_index(drop=True),
        test=ordered.iloc[val_end:].reset_index(drop=True),
    )


def frame_dataset_hash(frame: pd.DataFrame) -> str:
    """Return a stable hash for a training dataframe."""
    import hashlib

    digest = hashlib.sha256()
    hashed = pd.util.hash_pandas_object(frame, index=True).to_numpy(dtype=np.uint64)
    digest.update(hashed.tobytes())
    return digest.hexdigest()
