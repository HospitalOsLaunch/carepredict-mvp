"""Feature fetching boundary for Feast online features."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from services.api.schemas.prediction import ChargePredictionRequest


@dataclass(frozen=True, slots=True)
class FeatureBundle:
    """Historical and current features needed by the prediction endpoint."""

    history: pd.DataFrame
    current_charge: float


class FeastFeatureFetcher:
    """Fetch online/offline features for serving.

    The MVP implementation returns deterministic local features when Feast is not
    configured in-process. The class boundary keeps the endpoint ready for the
    pass 1 Feast online store without coupling tests to Redis.
    """

    def fetch(self, request: ChargePredictionRequest) -> FeatureBundle:
        """Fetch a 24h history frame for the requested service."""
        timestamps = pd.date_range(end=request.timestamp, periods=24, freq="h")
        base = 58.0 if request.service_id.startswith("urg") else 48.0
        values = [base + (hour % 6) * 0.4 for hour in range(24)]
        history = pd.DataFrame(
            {
                "timestamp": timestamps,
                "service_id": [request.service_id] * 24,
                "hospital_profile": ["acute"] * 24,
                "siips_score": values,
            }
        )
        return FeatureBundle(history=history, current_charge=float(values[-1]))


def get_feature_fetcher() -> FeastFeatureFetcher:
    """Return the feature fetcher dependency."""
    return FeastFeatureFetcher()
