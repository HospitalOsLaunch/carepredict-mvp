"""Behavioral tests for the v2 action-free forecast endpoint."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.routers.forecast import get_v2_forecast_service, router
from services.api.schemas.forecast import ForecastResponse
from services.ml.forecasting.v2_service import V2ForecastService

ARTIFACT_DIR = Path("artifacts/v2_forecast_multi")
CLINICAL_SIIPS_MIN = 100.0
CLINICAL_SIIPS_MAX = 2000.0


@pytest.fixture(scope="module")
def v2_service() -> V2ForecastService:
    """Return a v2 forecast service backed by local artifacts."""
    if not ARTIFACT_DIR.exists():
        pytest.skip("v2 forecast artifacts are unavailable")
    return V2ForecastService.from_artifacts(ARTIFACT_DIR)


@pytest.fixture(scope="module")
def client(v2_service: V2ForecastService) -> Iterator[TestClient]:
    """Create a test app with dependency-injected v2 forecast service."""
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_v2_forecast_service] = lambda: v2_service
    with TestClient(app) as test_client:
        yield test_client


def _feature_step(index: int) -> dict[str, float]:
    return {
        "admissions_h": float(index % 4),
        "discharges_h": float((index + 1) % 3),
        "nurse_count": 12.0 + float(index % 3),
        "aide_count": 8.0 + float(index % 2),
        "overtime_hours": float(index % 2),
        "patient_count": 30.0 + float(index % 8),
        "occupancy_rate": 0.70 + 0.01 * float(index % 8),
    }


def _payload(horizon: int = 12) -> dict[str, object]:
    return {
        "hospital_id": "hosp-001",
        "service_id": "urg-001",
        "origin_timestamp": "2025-07-08T00:00:00Z",
        "history": [_feature_step(index) for index in range(120)],
        "horizon": horizon,
    }


def test_history_length_wrong_returns_422(client: TestClient) -> None:
    payload = _payload()
    payload["history"] = [_feature_step(index) for index in range(119)]

    response = client.post("/forecast/charge", json=payload)

    assert response.status_code == 422


def test_horizon_out_of_range_returns_422(client: TestClient) -> None:
    payload = _payload(horizon=49)

    response = client.post("/forecast/charge", json=payload)

    assert response.status_code == 422


def test_malformed_feature_step_returns_422(client: TestClient) -> None:
    payload = _payload()
    history = list(payload["history"])  # type: ignore[arg-type]
    malformed = dict(history[0])
    malformed.pop("occupancy_rate")
    history[0] = malformed
    payload["history"] = history

    response = client.post("/forecast/charge", json=payload)

    assert response.status_code == 422


def test_real_forecast_response_has_ordered_intervals_and_plausible_values(
    client: TestClient,
) -> None:
    response = client.post("/forecast/charge", json=_payload(horizon=24))

    assert response.status_code == 200
    parsed = ForecastResponse.model_validate(response.json())
    assert parsed.status == "ok"
    assert parsed.granularity == "daily_patch_24"
    assert len(parsed.results) == 24
    for step in parsed.results:
        assert step.lower_90 < step.predicted_siips < step.upper_90
        assert CLINICAL_SIIPS_MIN <= step.predicted_siips < CLINICAL_SIIPS_MAX


def test_forecast_is_deterministic_for_identical_request(client: TestClient) -> None:
    payload = _payload(horizon=12)

    first = client.post("/forecast/charge", json=payload)
    second = client.post("/forecast/charge", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


def test_forecast_service_is_cached_on_app_state(
    monkeypatch: pytest.MonkeyPatch,
    v2_service: V2ForecastService,
) -> None:
    calls = 0

    def fake_from_artifacts() -> V2ForecastService:
        nonlocal calls
        calls += 1
        return v2_service

    monkeypatch.setattr(V2ForecastService, "from_artifacts", staticmethod(fake_from_artifacts))
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as test_client:
        first = test_client.post("/forecast/charge", json=_payload(horizon=1))
        second = test_client.post("/forecast/charge", json=_payload(horizon=1))

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == 1
