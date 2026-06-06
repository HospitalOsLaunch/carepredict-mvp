"""API schema tests."""

from __future__ import annotations

from datetime import UTC, datetime

from services.api.schemas.prediction import ChargePredictionRequest, ChargePredictionResponse


def test_prediction_response_schema_exact_keys() -> None:
    response = ChargePredictionResponse(
        value=87,
        lower_90=81,
        upper_90=93,
        coverage=0.90,
        mape=0.09,
        crps=0.12,
        model_version="tft-moirai-ft-v1.0",
        attention_weights={"top_features": ["admissions_j0"]},
    )

    assert set(response.model_dump().keys()) == {
        "value",
        "lower_90",
        "upper_90",
        "coverage",
        "mape",
        "crps",
        "model_version",
        "attention_weights",
    }


def test_prediction_request_accepts_planned_interventions() -> None:
    request = ChargePredictionRequest(
        service_id="urg-001",
        hospital_id="hosp-001",
        timestamp=datetime(2026, 7, 15, 8, tzinfo=UTC),
        planned_interventions=[
            {
                "type": "discharge",
                "scheduled_at": "2026-07-15T11:00:00Z",
                "count": 3,
            }
        ],
    )

    assert request.planned_interventions[0].type == "discharge"
