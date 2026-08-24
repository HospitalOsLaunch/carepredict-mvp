"""Synthetic-only dataset adapter for TS-JEPA smoke training."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np
import torch
from torch import Tensor
from torch.utils.data import Dataset

from data.synthetic.siips_generator import DEFAULT_SERVICES, SyntheticDataset, generate_dataset
from rs_jepa.typing import Array

DEFAULT_CHANNELS: tuple[str, ...] = (
    "siips_score",
    "aas_score",
    "patient_count",
    "nurse_count",
    "aide_count",
    "overtime_hours",
    "avg_seniority_months",
    "admissions_count",
    "discharges_count",
    "occupancy_ratio",
    "hour_sin",
    "hour_cos",
    "weekday_sin",
)


@dataclass
class SyntheticDatasetConfig:
    """Configuration for the in-memory synthetic hospital dataset."""

    n_days: int = 60
    window_days: int = 7
    seed: int = 0
    split: str = "train"
    val_frac: float = 0.2
    channels: list[str] | None = None


class SyntheticHospitalDataset(Dataset[dict[str, Tensor]]):
    """Non-overlapping hourly windows from the calibrated synthetic SIIPS generator."""

    def __init__(self, cfg: SyntheticDatasetConfig) -> None:
        super().__init__()
        if cfg.n_days <= 0:
            raise ValueError("n_days must be strictly positive")
        if cfg.window_days <= 0:
            raise ValueError("window_days must be strictly positive")
        if cfg.split not in {"train", "val"}:
            raise ValueError("split must be 'train' or 'val'")
        if not 0.0 < cfg.val_frac < 1.0:
            raise ValueError("val_frac must be in (0, 1)")
        self.cfg = cfg
        self.channels = tuple(cfg.channels or DEFAULT_CHANNELS)
        self.window_hours = cfg.window_days * 24
        if self.window_hours % 24 != 0:
            raise AssertionError("window length must be divisible by 24")

        start = datetime(2024, 1, 1, tzinfo=UTC)
        dataset = generate_dataset(
            months=1,
            services=[DEFAULT_SERVICES[0]],
            seed=cfg.seed,
            start=start,
            end=start + timedelta(days=cfg.n_days),
        )
        series, siips = self._materialize(dataset)
        split_day = min(max(int(round(cfg.n_days * (1.0 - cfg.val_frac))), 1), cfg.n_days - 1)
        split_hour = split_day * 24
        if cfg.split == "train":
            series, siips = series[:split_hour], siips[:split_hour]
        else:
            series, siips = series[split_hour:], siips[split_hour:]
        if not np.isfinite(series).all() or not np.isfinite(siips).all():
            raise AssertionError("synthetic tensors must not contain NaN or Inf")
        self.series = torch.tensor(series, dtype=torch.float32)
        self.siips = torch.tensor(siips, dtype=torch.float32)

    def __len__(self) -> int:
        """Return the number of complete non-overlapping windows."""
        return int(self.series.shape[0] // self.window_hours)

    def __getitem__(self, index: int) -> dict[str, Tensor]:
        """Return one non-overlapping window with aligned SIIPS targets."""
        if index < 0 or index >= len(self):
            raise IndexError(index)
        start = index * self.window_hours
        end = start + self.window_hours
        series = self.series[start:end]
        siips = self.siips[start:end]
        if series.shape[0] != self.window_hours or siips.shape[0] != self.window_hours:
            raise AssertionError("window is incomplete")
        if series.shape[0] % 24 != 0:
            raise AssertionError("window length must be divisible by 24")
        return {"series": series, "siips": siips}

    def _materialize(self, dataset: SyntheticDataset) -> tuple[Array, Array]:
        """Convert generated records into aligned hourly arrays."""
        care_load = sorted(dataset.care_load, key=lambda record: record.measured_at)
        staffing = sorted(dataset.staffing, key=lambda record: record.shift_start)
        if len(care_load) != self.cfg.n_days * 24:
            raise AssertionError("care_load length does not match requested hourly horizon")
        if len(staffing) != len(care_load):
            raise AssertionError("staffing and care_load must align one-to-one")
        self._assert_hourly([record.measured_at for record in care_load])
        self._assert_hourly([record.shift_start for record in staffing])

        admission_counts = self._event_counts(
            timestamps=[record.measured_at for record in care_load],
            event_times=[record.admission_time for record in dataset.admissions],
        )
        discharge_counts = self._event_counts(
            timestamps=[record.measured_at for record in care_load],
            event_times=[record.discharge_time for record in dataset.discharges],
        )
        service = dataset.services[0]
        rows: list[list[float]] = []
        siips_values: list[float] = []
        for index, (load, staff) in enumerate(zip(care_load, staffing, strict=True)):
            if load.measured_at != staff.shift_start:
                raise AssertionError("staffing and care_load timestamps must match")
            values = {
                "siips_score": float(load.siips_score),
                "aas_score": float(load.aas_score),
                "patient_count": float(load.patient_count),
                "nurse_count": float(staff.nurse_count),
                "aide_count": float(staff.aide_count),
                "overtime_hours": float(staff.overtime_hours),
                "avg_seniority_months": float(staff.avg_seniority_months),
                "admissions_count": float(admission_counts[index]),
                "discharges_count": float(discharge_counts[index]),
                "occupancy_ratio": float(load.patient_count) / float(service.bed_count),
                "hour_sin": float(np.sin(2.0 * np.pi * load.measured_at.hour / 24.0)),
                "hour_cos": float(np.cos(2.0 * np.pi * load.measured_at.hour / 24.0)),
                "weekday_sin": float(np.sin(2.0 * np.pi * load.measured_at.weekday() / 7.0)),
            }
            missing = set(self.channels).difference(values)
            if missing:
                raise ValueError(f"unknown synthetic channels: {sorted(missing)}")
            rows.append([values[channel] for channel in self.channels])
            siips_values.append(float(load.siips_score))
        return np.asarray(rows, dtype=np.float32), np.asarray(siips_values, dtype=np.float32)

    @staticmethod
    def _assert_hourly(timestamps: Sequence[datetime]) -> None:
        """Assert a strictly hourly timestamp sequence."""
        if not timestamps:
            raise AssertionError("timestamp sequence must not be empty")
        for left, right in zip(timestamps, timestamps[1:], strict=False):
            delta_hours = (right - left).total_seconds() / 3600.0
            if delta_hours != 1.0:
                raise AssertionError("synthetic series must have hourly granularity")

    @staticmethod
    def _event_counts(
        timestamps: Sequence[datetime], event_times: Sequence[datetime]
    ) -> Array:
        """Count events in each hourly bucket aligned to ``timestamps``."""
        hour_to_index = {timestamp: index for index, timestamp in enumerate(timestamps)}
        counts = np.zeros(len(timestamps), dtype=np.float32)
        for event_time in event_times:
            bucket = event_time.replace(minute=0, second=0, microsecond=0)
            index = hour_to_index.get(bucket)
            if index is not None:
                counts[index] += np.float32(1.0)
        return counts


def build_synthetic_dataset(cfg: SyntheticDatasetConfig) -> SyntheticHospitalDataset:
    """Build an in-memory deterministic synthetic hospital dataset."""
    return SyntheticHospitalDataset(cfg)
