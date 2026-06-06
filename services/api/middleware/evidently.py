"""Evidently-compatible prediction logging middleware helpers."""

from __future__ import annotations

from pathlib import Path

import structlog

from services.api.schemas.prediction import ChargePredictionRequest, ChargePredictionResponse

LOGGER = structlog.get_logger(__name__)


class EvidentlyPredictionLogger:
    """Append prediction events for downstream Evidently drift reports."""

    def __init__(self, log_path: Path = Path("reports/evidently/predictions.jsonl")) -> None:
        self.log_path = log_path

    def log_prediction(
        self,
        request: ChargePredictionRequest,
        response: ChargePredictionResponse,
    ) -> None:
        """Log a prediction event as structured JSON."""
        import json

        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "service_id": request.service_id,
            "hospital_id": request.hospital_id,
            "timestamp": request.timestamp.isoformat(),
            "value": response.value,
            "lower_90": response.lower_90,
            "upper_90": response.upper_90,
            "model_version": response.model_version,
            "top_features": response.attention_weights.top_features,
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")
        LOGGER.info("prediction_logged_for_drift", **payload)


def get_evidently_logger() -> EvidentlyPredictionLogger:
    """Return the prediction drift logger."""
    return EvidentlyPredictionLogger()
