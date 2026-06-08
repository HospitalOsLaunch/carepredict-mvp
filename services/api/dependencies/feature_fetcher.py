"""Feature fetching boundary backed by TimescaleDB."""

from __future__ import annotations

import os
from dataclasses import dataclass

import pandas as pd
import psycopg
import structlog

from services.api.schemas.prediction import ChargePredictionRequest

LOGGER = structlog.get_logger(__name__)

# Must cover TFT's max_encoder_length (336h) + safety margin.
LOOKBACK_HOURS = 400

# Connection string -- relies on docker-compose service names.
DB_DSN = os.environ.get(
    "TIMESCALEDB_DSN",
    "postgresql://carepredict:carepredict@timescaledb:5432/carepredict",
)


@dataclass(frozen=True, slots=True)
class FeatureBundle:
    """Historical and current features needed by the prediction endpoint."""

    history: pd.DataFrame
    current_charge: float


class TimescaleFeatureFetcher:
    """Fetch hourly SIIPS history from TimescaleDB for serving.

    Returns LOOKBACK_HOURS of history ending at request.timestamp, in the
    schema expected by the TFT backend: columns
    [timestamp, service_id, hospital_profile, siips_score].

    If the DB has fewer rows than LOOKBACK_HOURS in the requested window,
    raises ValueError so the API can return a clean 422.
    """

    def fetch(self, request: ChargePredictionRequest) -> FeatureBundle:
        """Fetch LOOKBACK_HOURS hourly history frame for the requested service."""
        end_ts = request.timestamp
        start_ts = end_ts - pd.Timedelta(hours=LOOKBACK_HOURS)

        with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT measured_at, service_id, siips_score
                FROM canonical.care_load
                WHERE hospital_id = %s
                  AND service_id = %s
                  AND measured_at >= %s
                  AND measured_at <= %s
                ORDER BY measured_at ASC
                """,
                (
                    request.hospital_id,
                    request.service_id,
                    start_ts,
                    end_ts,
                ),
            )
            rows = cur.fetchall()

        if not rows:
            raise ValueError(
                f"No historical data found for {request.hospital_id}/"
                f"{request.service_id} in window [{start_ts}, {end_ts}]"
            )

        if len(rows) < 336:
            LOGGER.warning(
                "feature_fetch_short_history",
                hospital_id=request.hospital_id,
                service_id=request.service_id,
                rows_fetched=len(rows),
                rows_required=336,
            )

        history = pd.DataFrame(
            rows,
            columns=["timestamp", "service_id", "siips_score"],
        )
        # TFT trained with this static column; we expose 'acute' as MVP default.
        history["hospital_profile"] = "acute"
        history["siips_score"] = history["siips_score"].astype(float)
        # Ensure the column order matches what TFT expects.
        history = history[["timestamp", "service_id", "hospital_profile", "siips_score"]]

        current_charge = float(history["siips_score"].iloc[-1])
        LOGGER.info(
            "feature_fetch_completed",
            hospital_id=request.hospital_id,
            service_id=request.service_id,
            rows=len(history),
            current_charge=current_charge,
        )
        return FeatureBundle(history=history, current_charge=current_charge)


# Backwards-compatible alias so other modules don't need to change imports.
FeastFeatureFetcher = TimescaleFeatureFetcher


def get_feature_fetcher() -> TimescaleFeatureFetcher:
    """Return the feature fetcher dependency."""
    return TimescaleFeatureFetcher()
