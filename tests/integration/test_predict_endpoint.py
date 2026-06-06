"""Prediction endpoint integration smoke test."""

from __future__ import annotations

from fastapi.testclient import TestClient

from services.api.main import app


def test_predict_endpoint_response_shape() -> None:
    client = TestClient(app)

    response = client.post(
        "/predict/charge",
        json={
            "service_id": "urg-001",
            "hospital_id": "hosp-001",
            "timestamp": "2026-07-15T08:00:00Z",
            "planned_interventions": [
                {"type": "discharge", "scheduled_at": "2026-07-15T11:00:00Z", "count": 3},
                {"type": "surgery", "scheduled_at": "2026-07-15T14:00:00Z", "count": 2},
            ],
        },
    )

    assert response.status_code == 200
    assert set(response.json().keys()) == {
        "value",
        "lower_90",
        "upper_90",
        "coverage",
        "mape",
        "crps",
        "model_version",
        "attention_weights",
    }
