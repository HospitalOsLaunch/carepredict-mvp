"""Read-only canonical feature-window fetcher for v2 forecasts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from services.api.dependencies.feature_fetcher import DB_DSN
from services.api.schemas.history import FEATURE_WINDOW_CHANNELS
from services.ml.forecasting.v2_forecast import (
    V2ForecastArtifacts,
    history_window_origin,
    v2_forecast_history_length,
)


@dataclass(frozen=True, slots=True)
class FeatureWindow:
    """Canonical feature window ready for API serialization."""

    service_id: str
    hospital_id: str
    origin_timestamp: datetime
    length: int
    channels: list[str]
    history: list[list[float]]


class FeatureWindowNotFoundError(ValueError):
    """Raised when canonical data cannot provide the requested feature window."""


class TimescaleFeatureWindowFetcher:
    """Fetch v2 forecast feature windows from canonical TimescaleDB tables."""

    def fetch(
        self,
        *,
        hospital_id: str,
        service_id: str,
        origin_timestamp: datetime,
        length: int,
        artifacts: V2ForecastArtifacts,
    ) -> FeatureWindow:
        """Fetch an exactly aligned 7-channel feature window."""
        expected_length = v2_forecast_history_length(artifacts)
        if length != expected_length:
            raise FeatureWindowNotFoundError(
                f"length must be {expected_length} for the loaded v2 forecast artifacts"
            )
        origin = _to_utc(origin_timestamp)
        history_end = history_window_origin(artifacts, origin)
        history_start = history_end - timedelta(hours=length - 1)

        with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
            service = self._fetch_service(cur, hospital_id=hospital_id, service_id=service_id)
            if service is None:
                raise FeatureWindowNotFoundError(
                    f"unknown service_id/hospital_id: {hospital_id}/{service_id}"
                )
            min_time, max_time = self._fetch_care_load_range(
                cur,
                hospital_id=hospital_id,
                service_id=service_id,
            )
            if min_time is None or max_time is None:
                raise FeatureWindowNotFoundError(
                    f"no canonical care_load rows found for {hospital_id}/{service_id}"
                )
            if history_start < min_time:
                raise FeatureWindowNotFoundError(
                    f"insufficient history before {origin.isoformat()} for length {length}"
                )
            if history_end > max_time:
                raise FeatureWindowNotFoundError(
                    f"origin_timestamp {origin.isoformat()} is outside available canonical range"
                )

            care_load = self._fetch_care_load(
                cur,
                hospital_id=hospital_id,
                service_id=service_id,
                start=history_start,
                end=history_end,
            )
            staffing = self._fetch_staffing(
                cur,
                hospital_id=hospital_id,
                service_id=service_id,
                start=history_start,
                end=history_end,
            )
            admissions = self._fetch_event_counts(
                cur,
                table="canonical.admissions",
                time_column="admission_time",
                hospital_id=hospital_id,
                service_id=service_id,
                start=history_start,
                end=history_end,
            )
            discharges = self._fetch_event_counts(
                cur,
                table="canonical.discharges",
                time_column="discharge_time",
                hospital_id=hospital_id,
                service_id=service_id,
                start=history_start,
                end=history_end,
            )

        history = _build_history(
            service=service,
            care_load=care_load,
            staffing=staffing,
            admissions=admissions,
            discharges=discharges,
            start=history_start,
            length=length,
        )
        return FeatureWindow(
            service_id=service_id,
            hospital_id=hospital_id,
            origin_timestamp=origin,
            length=length,
            channels=list(FEATURE_WINDOW_CHANNELS),
            history=history,
        )

    def _fetch_service(
        self,
        cur: Any,
        *,
        hospital_id: str,
        service_id: str,
    ) -> dict[str, Any] | None:
        cur.execute(
            """
            SELECT hospital_id, service_id, bed_count
            FROM canonical.services
            WHERE hospital_id = %s
              AND service_id = %s
            ORDER BY service_id ASC
            """,
            (hospital_id, service_id),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {"hospital_id": row[0], "service_id": row[1], "bed_count": row[2]}

    def _fetch_care_load_range(
        self,
        cur: Any,
        *,
        hospital_id: str,
        service_id: str,
    ) -> tuple[datetime | None, datetime | None]:
        cur.execute(
            """
            SELECT MIN(measured_at), MAX(measured_at)
            FROM canonical.care_load
            WHERE hospital_id = %s
              AND service_id = %s
            """,
            (hospital_id, service_id),
        )
        row = cur.fetchone()
        if row is None:
            return None, None
        return _maybe_utc(row[0]), _maybe_utc(row[1])

    def _fetch_care_load(
        self,
        cur: Any,
        *,
        hospital_id: str,
        service_id: str,
        start: datetime,
        end: datetime,
    ) -> dict[datetime, dict[str, Any]]:
        cur.execute(
            """
            SELECT
                c.measured_at,
                c.siips_score,
                c.patient_count
            FROM canonical.care_load c
            WHERE c.hospital_id = %s
              AND c.service_id = %s
              AND c.measured_at >= %s
              AND c.measured_at <= %s
            ORDER BY c.measured_at ASC
            """,
            (hospital_id, service_id, start, end),
        )
        return {
            _to_utc(measured_at): {
                "siips": siips_score,
                "patient_count": patient_count,
            }
            for measured_at, siips_score, patient_count in cur.fetchall()
        }

    def _fetch_staffing(
        self,
        cur: Any,
        *,
        hospital_id: str,
        service_id: str,
        start: datetime,
        end: datetime,
    ) -> dict[datetime, dict[str, Any]]:
        cur.execute(
            """
            SELECT
                s.shift_start,
                s.nurse_count,
                s.aide_count,
                s.overtime_hours
            FROM canonical.staffing s
            WHERE s.hospital_id = %s
              AND s.service_id = %s
              AND s.shift_start >= %s
              AND s.shift_start <= %s
            ORDER BY s.shift_start ASC
            """,
            (hospital_id, service_id, start, end),
        )
        return {
            _to_utc(shift_start): {
                "nurse_count": nurse_count,
                "aide_count": aide_count,
                "overtime_hours": overtime_hours,
            }
            for shift_start, nurse_count, aide_count, overtime_hours in cur.fetchall()
        }

    def _fetch_event_counts(
        self,
        cur: Any,
        *,
        table: str,
        time_column: str,
        hospital_id: str,
        service_id: str,
        start: datetime,
        end: datetime,
    ) -> dict[datetime, float]:
        cur.execute(
            f"""
            SELECT
                date_trunc('hour', e.{time_column}) AS measured_at,
                COUNT(*)::DOUBLE PRECISION AS n_events
            FROM {table} e
            WHERE e.hospital_id = %s
              AND e.service_id = %s
              AND e.{time_column} >= %s
              AND e.{time_column} < %s
            GROUP BY date_trunc('hour', e.{time_column})
            ORDER BY measured_at ASC
            """,
            (hospital_id, service_id, start, end + timedelta(hours=1)),
        )
        return {_to_utc(measured_at): float(n_events) for measured_at, n_events in cur.fetchall()}


def _build_history(
    *,
    service: dict[str, Any],
    care_load: dict[datetime, dict[str, Any]],
    staffing: dict[datetime, dict[str, Any]],
    admissions: dict[datetime, float],
    discharges: dict[datetime, float],
    start: datetime,
    length: int,
) -> list[list[float]]:
    history: list[list[float]] = []
    for offset in range(length):
        measured_at = start + timedelta(hours=offset)
        care = care_load.get(measured_at)
        staff = staffing.get(measured_at)
        if care is None or staff is None:
            raise FeatureWindowNotFoundError(
                f"incomplete canonical row at {measured_at.isoformat()}"
            )
        patient_count = _required_float(care["patient_count"], "patient_count", measured_at)
        bed_count = _required_float(service["bed_count"], "bed_count", measured_at)
        row = [
            float(admissions.get(measured_at, 0.0)),
            float(discharges.get(measured_at, 0.0)),
            _required_float(staff["nurse_count"], "nurse_count", measured_at),
            _required_float(staff["aide_count"], "aide_count", measured_at),
            _required_float(staff["overtime_hours"], "overtime_hours", measured_at),
            patient_count,
            patient_count / bed_count,
        ]
        history.append(row)
    return history


def _required_float(value: Any, name: str, measured_at: datetime) -> float:
    if value is None:
        raise FeatureWindowNotFoundError(f"missing {name} at {measured_at.isoformat()}")
    return float(value)


def _maybe_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    return _to_utc(value)


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
