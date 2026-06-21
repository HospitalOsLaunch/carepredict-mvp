"""Behavioral tests for canonical feature-window endpoint."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from data.synthetic.siips_generator import db_config_from_env
from scripts.forecast_realism_check import _fetch_rows, _history_rows
from services.api.dependencies import feature_window_fetcher as window_fetcher_module
from services.api.routers.forecast import (
    get_v2_forecast_service,
)
from services.api.routers.forecast import (
    router as forecast_router,
)
from services.api.routers.history import router as history_router
from services.api.schemas.history import FEATURE_WINDOW_CHANNELS
from services.ml.forecasting.v2_forecast import history_window_origin as model_history_window_origin
from services.ml.forecasting.v2_service import V2ForecastService

ARTIFACT_DIR = Path("artifacts/v2_forecast_multi")
CLINICAL_SIIPS_MIN = 100.0
CLINICAL_SIIPS_MAX = 2000.0
ORIGIN = "2025-07-08T00:00:00Z"


def _local_dsn() -> str:
    config = db_config_from_env()
    return (
        f"postgresql://{config['user']}:{config['password']}"
        f"@{config['host']}:{config['port']}/{config['dbname']}"
    )


@pytest.fixture(scope="module")
def v2_service() -> V2ForecastService:
    """Return a v2 forecast service backed by local artifacts."""
    if not ARTIFACT_DIR.exists():
        pytest.skip("v2 forecast artifacts are unavailable")
    dsn = _local_dsn()
    try:
        with psycopg.connect(dsn, connect_timeout=1):
            pass
    except Exception as exc:
        pytest.skip(f"TimescaleDB is unavailable: {exc}")
    window_fetcher_module.DB_DSN = dsn
    try:
        return V2ForecastService.from_artifacts(ARTIFACT_DIR)
    except Exception as exc:
        pytest.skip(f"v2 forecast artifacts are unavailable: {exc}")


@pytest.fixture(scope="module")
def client(v2_service: V2ForecastService) -> Iterator[TestClient]:
    """Create a test app with history and forecast routes."""
    app = FastAPI()
    app.include_router(history_router)
    app.include_router(forecast_router)
    app.dependency_overrides[get_v2_forecast_service] = lambda: v2_service
    with TestClient(app) as test_client:
        yield test_client


def _history_params(
    *,
    service_id: str = "urg-001",
    hospital_id: str = "hosp-001",
    origin: str = ORIGIN,
    length: int = 120,
) -> dict[str, str | int]:
    return {
        "hospital_id": hospital_id,
        "service_id": service_id,
        "origin_timestamp": origin,
        "length": length,
    }


def test_valid_feature_window_returns_120_by_7_without_siips(client: TestClient) -> None:
    response = client.get("/history/feature-window", params=_history_params())

    assert response.status_code == 200
    payload = response.json()
    assert payload["length"] == 120
    assert payload["channels"] == list(FEATURE_WINDOW_CHANNELS)
    assert "siips" not in payload["channels"]
    assert len(payload["history"]) == 120
    assert all(len(row) == 7 for row in payload["history"])


def test_feature_window_matches_realism_check_exactly(
    client: TestClient,
    v2_service: V2ForecastService,
) -> None:
    response = client.get("/history/feature-window", params=_history_params())
    assert response.status_code == 200
    payload = response.json()

    origin = datetime(2025, 7, 8, tzinfo=UTC)
    rows = _fetch_rows(service_id="urg-001", train_end="2025-07-01")
    by_time = {row["measured_at"]: row for row in rows}
    expected_dicts = _history_rows(
        artifacts=v2_service.artifacts,
        by_time=by_time,
        origin=origin,
    )
    expected_rows = [
        [step[channel] for channel in FEATURE_WINDOW_CHANNELS]
        for step in expected_dicts
    ]

    assert payload["history"] == expected_rows


def _forecast_max_from_history(
    client: TestClient,
    payload: dict,
    *,
    origin: str,
) -> float:
    channels = payload["channels"]
    forecast_history = [
        dict(zip(channels, row, strict=True))
        for row in payload["history"]
    ]
    response = client.post(
        "/forecast/charge",
        json={
            "hospital_id": payload["hospital_id"],
            "service_id": payload["service_id"],
            "origin_timestamp": origin,
            "history": forecast_history,
            "horizon": 48,
        },
    )
    assert response.status_code == 200
    return max(step["predicted_siips"] for step in response.json()["results"])


def test_feature_window_and_forecast_are_invariant_across_same_day_origin_hours(
    client: TestClient,
) -> None:
    origins = [
        f"2025-07-08T{hour:02d}:00:00Z"
        for hour in (0, 3, 9, 14, 18, 23)
    ]
    payloads = []
    fc_maxes = []
    for origin in origins:
        response = client.get("/history/feature-window", params=_history_params(origin=origin))
        assert response.status_code == 200
        payload = response.json()
        payloads.append(payload)
        fc_maxes.append(_forecast_max_from_history(client, payload, origin=origin))

    reference = np.asarray(payloads[0]["history"], dtype=float)
    for payload in payloads[1:]:
        assert np.allclose(np.asarray(payload["history"], dtype=float), reference)
    assert np.allclose(fc_maxes, fc_maxes[0])


def test_midnight_origin_is_noop_against_model_origin_logic(v2_service: V2ForecastService) -> None:
    origin = datetime(2025, 7, 8, tzinfo=UTC)
    assert window_fetcher_module.history_window_origin(v2_service.artifacts, origin) == (
        model_history_window_origin(v2_service.artifacts, origin)
    )


def test_strict_alignment_rejects_non_midnight_origin(v2_service: V2ForecastService) -> None:
    origin = datetime(2025, 7, 8, 9, tzinfo=UTC)
    with pytest.raises(window_fetcher_module.FeatureWindowNotFoundError, match="00:00:00 UTC"):
        window_fetcher_module.history_window_origin(
            v2_service.artifacts,
            origin,
            strict=True,
        )


def test_unknown_service_returns_422(client: TestClient) -> None:
    response = client.get(
        "/history/feature-window",
        params=_history_params(service_id="unknown-001"),
    )

    assert response.status_code == 422


def test_wrong_hospital_returns_422(client: TestClient) -> None:
    response = client.get(
        "/history/feature-window",
        params=_history_params(hospital_id="hosp-999"),
    )

    assert response.status_code == 422


def test_origin_too_early_returns_422(client: TestClient) -> None:
    response = client.get(
        "/history/feature-window",
        params=_history_params(origin="2024-01-02T00:00:00Z"),
    )

    assert response.status_code == 422


def test_origin_beyond_available_range_returns_422(client: TestClient) -> None:
    response = client.get(
        "/history/feature-window",
        params=_history_params(origin="2026-01-05T00:00:00Z"),
    )

    assert response.status_code == 422


def test_history_window_feeds_forecast_endpoint(client: TestClient) -> None:
    history_response = client.get("/history/feature-window", params=_history_params())
    assert history_response.status_code == 200
    history_payload = history_response.json()
    channels = history_payload["channels"]
    forecast_history = [
        dict(zip(channels, row, strict=True))
        for row in history_payload["history"]
    ]

    forecast_response = client.post(
        "/forecast/charge",
        json={
            "hospital_id": history_payload["hospital_id"],
            "service_id": history_payload["service_id"],
            "origin_timestamp": history_payload["origin_timestamp"],
            "history": forecast_history,
            "horizon": 24,
        },
    )

    assert forecast_response.status_code == 200
    forecast_payload = forecast_response.json()
    assert len(forecast_payload["results"]) == 24
    for step in forecast_payload["results"]:
        assert step["lower_90"] < step["predicted_siips"] < step["upper_90"]
        assert CLINICAL_SIIPS_MIN <= step["predicted_siips"] < CLINICAL_SIIPS_MAX
