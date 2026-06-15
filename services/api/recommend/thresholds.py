"""Per-service risk thresholds for recommendation calibration."""

from __future__ import annotations

import os
from typing import Protocol

import psycopg
import structlog

LOGGER = structlog.get_logger(__name__)
DEFAULT_RISK_THRESHOLD = 1600.0


class ServiceThresholdProvider(Protocol):
    """Provider for service-specific SIIPS risk thresholds."""

    def threshold_for(self, *, hospital_id: str, service_id: str) -> float:
        """Return the SIIPS risk threshold for one service."""


class TimescaleP90ThresholdProvider:
    """Read service-specific P90 SIIPS thresholds from canonical TimescaleDB.

    Thresholds are computed over the full canonical service history, with no
    origin time filter, so the recommendation baseline is stable across dates.
    Missing services fall back to ``DEFAULT_RISK_THRESHOLD`` and log a warning.
    """

    def __init__(
        self,
        *,
        dsn: str | None = None,
        connect_factory=psycopg.connect,
        fallback_threshold: float = DEFAULT_RISK_THRESHOLD,
    ) -> None:
        self.dsn = dsn or _timescale_dsn()
        self.connect_factory = connect_factory
        self.fallback_threshold = fallback_threshold
        self._cache: dict[tuple[str, str], float] = {}

    def threshold_for(self, *, hospital_id: str, service_id: str) -> float:
        """Return cached P90 threshold for one hospital/service pair."""
        cache_key = (hospital_id, service_id)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        with self.connect_factory(self.dsn) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT percentile_cont(0.9) WITHIN GROUP (ORDER BY siips_score)
                FROM canonical.care_load
                WHERE hospital_id = %s
                  AND service_id = %s
                """,
                (hospital_id, service_id),
            )
            row = cur.fetchone()

        value = None if row is None else row[0]
        if value is None:
            LOGGER.warning(
                "service_threshold_missing_using_fallback",
                hospital_id=hospital_id,
                service_id=service_id,
                fallback_threshold=self.fallback_threshold,
            )
            threshold = self.fallback_threshold
        else:
            threshold = float(value)

        self._cache[cache_key] = threshold
        return threshold


def _timescale_dsn() -> str:
    """Return a TimescaleDB DSN from the serving environment."""
    explicit = os.environ.get("TIMESCALEDB_DSN")
    if explicit:
        return explicit

    host = os.environ.get("TIMESCALE_HOST") or os.environ.get("POSTGRES_HOST") or "timescaledb"
    port = os.environ.get("TIMESCALE_PORT") or os.environ.get("POSTGRES_PORT") or "5432"
    database = os.environ.get("TIMESCALE_DB") or os.environ.get("POSTGRES_DB") or "carepredict"
    user = os.environ.get("TIMESCALE_USER") or os.environ.get("POSTGRES_USER") or "carepredict"
    password = (
        os.environ.get("TIMESCALE_PASSWORD")
        or os.environ.get("POSTGRES_PASSWORD")
        or "carepredict"
    )
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"
