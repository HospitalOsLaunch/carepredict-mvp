"""TimescaleDB adapter for canonical hospital time-series windows."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import numpy as np
import torch
from torch import Tensor
from torch.utils.data import Dataset

from data.synthetic.siips_generator import db_config_from_env

CHANNEL_NAMES: tuple[str, ...] = (
    "admissions_h",
    "discharges_h",
    "nurse_count",
    "aide_count",
    "overtime_hours",
    "patient_count",
    "occupancy_rate",
)


@dataclass
class TimescaleDatasetConfig:
    """Configuration for canonical TimescaleDB JEPA/RSSM datasets."""

    window_days: int = 7
    split: str = "train"
    train_end: str = "2025-07-01"
    services: list[str] | None = None
    db_overrides: dict[str, Any] | None = None


@dataclass(frozen=True)
class _Window:
    service_id: str
    start: datetime
    end: datetime
    series: np.ndarray
    siips: np.ndarray


class TimescaleHospitalDataset(Dataset[dict[str, Tensor]]):
    """Non-overlapping per-service windows from canonical TimescaleDB tables."""

    channel_names: tuple[str, ...] = CHANNEL_NAMES

    def __init__(self, cfg: TimescaleDatasetConfig) -> None:
        super().__init__()
        if cfg.window_days <= 0:
            raise ValueError("window_days must be strictly positive")
        if cfg.split not in {"train", "val"}:
            raise ValueError("split must be 'train' or 'val'")
        self.cfg = cfg
        self.window_hours = cfg.window_days * 24
        if self.window_hours % 24 != 0:
            raise AssertionError("window length must be divisible by 24")
        self.train_end = _parse_utc(cfg.train_end)
        self.n_rejected_windows = 0

        rows = self._fetch_rows()
        windows = self._build_windows(rows)
        if not windows:
            raise ValueError("no complete Timescale windows available for requested split")
        self._windows = windows

    def __len__(self) -> int:
        """Return total complete windows across services."""
        return len(self._windows)

    def __getitem__(self, index: int) -> dict[str, Tensor]:
        """Return one service/window sample with JEPA/RSSM tensor contract."""
        if index < 0 or index >= len(self):
            raise IndexError(index)
        window = self._windows[index]
        if window.series.shape[0] % 24 != 0:
            raise AssertionError("window length must be divisible by 24")
        return {
            "series": torch.tensor(window.series, dtype=torch.float32),
            "siips": torch.tensor(window.siips, dtype=torch.float32),
        }

    @property
    def window_starts(self) -> list[datetime]:
        """Return deterministic window start timestamps for tests and diagnostics."""
        return [window.start for window in self._windows]

    @property
    def window_ends(self) -> list[datetime]:
        """Return deterministic exclusive window end timestamps for tests and diagnostics."""
        return [window.end for window in self._windows]

    @property
    def service_ids(self) -> list[str]:
        """Return deterministic service ids aligned with dataset windows."""
        return [window.service_id for window in self._windows]

    def _fetch_rows(self) -> list[dict[str, Any]]:
        config = db_config_from_env()
        if self.cfg.db_overrides:
            config.update(self.cfg.db_overrides)
        psycopg2 = _psycopg2()
        with psycopg2.connect(**config) as connection:
            with connection.cursor() as cursor:
                services = self._fetch_services(cursor)
                care_load = self._fetch_care_load(cursor)
                staffing = self._fetch_staffing(cursor)
                admissions = self._fetch_event_counts(cursor, "canonical.admissions", "admission_time")
                discharges = self._fetch_event_counts(cursor, "canonical.discharges", "discharge_time")
        return self._build_hourly_rows(services, care_load, staffing, admissions, discharges)

    def _service_filter(self) -> tuple[str, tuple[Any, ...]]:
        if self.cfg.services is None:
            return "", ()
        return "service_id = ANY(%s)", (self.cfg.services,)

    def _fetch_services(self, cursor: Any) -> dict[str, dict[str, Any]]:
        service_filter, params = self._service_filter()
        cursor.execute(
            f"""
            SELECT hospital_id, service_id, bed_count
            FROM canonical.services
            {_where(service_filter)}
            ORDER BY service_id ASC
            """,
            params,
        )
        return {
            str(service_id): {
                "hospital_id": hospital_id,
                "service_id": service_id,
                "bed_count": bed_count,
            }
            for hospital_id, service_id, bed_count in cursor.fetchall()
        }

    def _fetch_care_load(self, cursor: Any) -> dict[tuple[str, datetime], dict[str, Any]]:
        service_filter, params = self._service_filter()
        where = _where(f"c.{service_filter}" if service_filter else "")
        cursor.execute(
            f"""
            SELECT
                c.service_id,
                c.measured_at,
                c.siips_score,
                c.patient_count
            FROM canonical.care_load c
            {where}
            ORDER BY c.service_id ASC, c.measured_at ASC
            """,
            params,
        )
        return {
            (str(service_id), _to_utc(measured_at)): {
                "siips": siips_score,
                "patient_count": patient_count,
            }
            for service_id, measured_at, siips_score, patient_count in cursor.fetchall()
        }

    def _fetch_staffing(self, cursor: Any) -> dict[tuple[str, datetime], dict[str, Any]]:
        service_filter, params = self._service_filter()
        where = _where(f"s.{service_filter}" if service_filter else "")
        cursor.execute(
            f"""
            SELECT
                s.service_id,
                s.shift_start,
                s.nurse_count,
                s.aide_count,
                s.overtime_hours
            FROM canonical.staffing s
            {where}
            ORDER BY s.service_id ASC, s.shift_start ASC
            """,
            params,
        )
        return {
            (str(service_id), _to_utc(shift_start)): {
                "nurse_count": nurse_count,
                "aide_count": aide_count,
                "overtime_hours": overtime_hours,
            }
            for service_id, shift_start, nurse_count, aide_count, overtime_hours in cursor.fetchall()
        }

    def _fetch_event_counts(self, cursor: Any, table: str, time_column: str) -> dict[tuple[str, datetime], float]:
        service_filter, params = self._service_filter()
        where = _where(f"e.{service_filter}" if service_filter else "")
        cursor.execute(
            f"""
            SELECT
                e.service_id,
                date_trunc('hour', e.{time_column}) AS measured_at,
                COUNT(*)::DOUBLE PRECISION AS n_events
            FROM {table} e
            {where}
            GROUP BY e.service_id, date_trunc('hour', e.{time_column})
            ORDER BY e.service_id ASC, measured_at ASC
            """,
            params,
        )
        return {
            (str(service_id), _to_utc(measured_at)): float(n_events)
            for service_id, measured_at, n_events in cursor.fetchall()
        }

    def _build_hourly_rows(
        self,
        services: dict[str, dict[str, Any]],
        care_load: dict[tuple[str, datetime], dict[str, Any]],
        staffing: dict[tuple[str, datetime], dict[str, Any]],
        admissions: dict[tuple[str, datetime], float],
        discharges: dict[tuple[str, datetime], float],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for service_id in sorted(services):
            service_times = sorted(timestamp for svc, timestamp in care_load if svc == service_id)
            if not service_times:
                continue
            for measured_at in _hourly_grid(service_times[0], service_times[-1]):
                care = care_load.get((service_id, measured_at), {})
                staff = staffing.get((service_id, measured_at), {})
                patient_count = care.get("patient_count")
                bed_count = services[service_id]["bed_count"]
                rows.append(
                    {
                        "hospital_id": services[service_id]["hospital_id"],
                        "service_id": service_id,
                        "measured_at": measured_at,
                        "admissions_h": admissions.get((service_id, measured_at), 0.0),
                        "discharges_h": discharges.get((service_id, measured_at), 0.0),
                        "nurse_count": staff.get("nurse_count"),
                        "aide_count": staff.get("aide_count"),
                        "overtime_hours": staff.get("overtime_hours"),
                        "patient_count": patient_count,
                        "occupancy_rate": None
                        if patient_count is None
                        else float(patient_count) / float(bed_count),
                        "siips": care.get("siips"),
                    }
                )
        return rows

    def _build_windows(self, rows: list[dict[str, Any]]) -> list[_Window]:
        by_service: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_service[str(row["service_id"])].append(row)

        windows: list[_Window] = []
        for service_id in sorted(by_service):
            service_rows = sorted(by_service[service_id], key=lambda row: row["measured_at"])
            timestamps = [_to_utc(row["measured_at"]) for row in service_rows]
            _assert_hourly(timestamps)
            series = np.asarray(
                [[_float_or_nan(row[channel]) for channel in self.channel_names] for row in service_rows],
                dtype=np.float32,
            )
            siips = np.asarray([_float_or_nan(row["siips"]) for row in service_rows], dtype=np.float32)
            series = _forward_fill_limit(series, limit=3)
            siips = _forward_fill_limit(siips[:, None], limit=3)[:, 0]

            max_start = len(service_rows) - self.window_hours + 1
            for start_index in range(0, max(max_start, 0), self.window_hours):
                end_index = start_index + self.window_hours
                start_ts = timestamps[start_index]
                end_ts = timestamps[end_index - 1].replace() if end_index <= len(timestamps) else None
                if end_ts is None:
                    continue
                exclusive_end = end_ts + (timestamps[1] - timestamps[0])
                if self.cfg.split == "train" and exclusive_end > self.train_end:
                    continue
                if self.cfg.split == "val" and start_ts < self.train_end:
                    continue
                window_series = series[start_index:end_index]
                window_siips = siips[start_index:end_index]
                if (
                    not _is_finite(window_series)
                    or not _is_finite(window_siips)
                    or bool(np.any(window_siips <= 0.0))
                ):
                    self.n_rejected_windows += 1
                    continue
                windows.append(
                    _Window(
                        service_id=service_id,
                        start=start_ts,
                        end=exclusive_end,
                        series=window_series.copy(),
                        siips=window_siips.copy(),
                    )
                )
        return windows


def build_timescale_dataset(cfg: TimescaleDatasetConfig) -> TimescaleHospitalDataset:
    """Build an in-memory canonical TimescaleDB hospital dataset."""
    return TimescaleHospitalDataset(cfg)


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _where(condition: str) -> str:
    if not condition:
        return ""
    return f"WHERE {condition}"


def _hourly_grid(start: datetime, end: datetime) -> list[datetime]:
    hours: list[datetime] = []
    current = start
    while current <= end:
        hours.append(current)
        current += timedelta(hours=1)
    return hours


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _float_or_nan(value: object) -> float:
    if value is None:
        return float("nan")
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _forward_fill_limit(values: np.ndarray, *, limit: int) -> np.ndarray:
    filled = values.astype(np.float32, copy=True)
    for col in range(filled.shape[1]):
        last = np.float32(np.nan)
        gap = 0
        for row in range(filled.shape[0]):
            value = filled[row, col]
            if np.isfinite(value):
                last = value
                gap = 0
            else:
                gap += 1
                if np.isfinite(last) and gap <= limit:
                    filled[row, col] = last
    return filled


def _is_finite(values: np.ndarray) -> bool:
    return bool(np.isfinite(values).all())


def _assert_hourly(timestamps: list[datetime]) -> None:
    if not timestamps:
        raise AssertionError("timestamp sequence must not be empty")
    for left, right in zip(timestamps, timestamps[1:], strict=False):
        if (right - left).total_seconds() != 3600.0:
            raise AssertionError("canonical series must have hourly granularity")


def _psycopg2() -> object:
    import psycopg2

    return psycopg2
