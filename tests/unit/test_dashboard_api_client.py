"""Unit tests for the dashboard FastAPI client."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
import requests

from dashboards.api_client import (
    ActionStep,
    SimulationRequest,
    WorldModelClient,
    WorldModelClientServerError,
    WorldModelClientUnreachable,
    WorldModelClientValidationError,
)


def build_request() -> SimulationRequest:
    """Build a valid minimal simulation request."""
    action = ActionStep(
        scheduled_admissions=1,
        scheduled_discharges=0,
        staff_redeployments=0,
        scheduled_surgeries=0,
        expected_transfers=0,
    )
    return SimulationRequest(
        hospital_id="hosp-001",
        service_id="urg-001",
        history_siips=[72.0] * 24,
        actions=[action],
    )


def response_mock(status_code: int, payload: dict[str, object] | None = None) -> Mock:
    """Create a minimal requests.Response-like mock."""
    response = Mock()
    response.status_code = status_code
    response.text = "error"
    response.json.return_value = payload or {}
    return response


def test_simulate_success() -> None:
    """A 200 response is parsed as a SimulationResponse."""
    payload = {
        "status": "ok",
        "hospital_id": "hosp-001",
        "service_id": "urg-001",
        "model_version": "rssm-world-model-v1",
        "results": [
            {
                "step_index": 0,
                "predicted_siips": 80.0,
                "lower_bound": 75.0,
                "upper_bound": 85.0,
                "reward": 0.0,
                "is_critical": False,
            }
        ],
    }
    with patch("requests.Session.request", return_value=response_mock(200, payload)):
        response = WorldModelClient().simulate(build_request())
    assert response.status == "ok"
    assert response.results[0].predicted_siips == 80.0


def test_simulate_validation_error() -> None:
    """A 422 response raises a typed validation error."""
    with (
        patch("requests.Session.request", return_value=response_mock(422)),
        pytest.raises(WorldModelClientValidationError),
    ):
        WorldModelClient().simulate(build_request())


def test_simulate_server_error() -> None:
    """A 500 response raises a typed server error."""
    with (
        patch("requests.Session.request", return_value=response_mock(500)),
        pytest.raises(WorldModelClientServerError),
    ):
        WorldModelClient().simulate(build_request())


def test_simulate_unreachable() -> None:
    """Connection failures are mapped to WorldModelClientUnreachable."""
    with (
        patch("requests.Session.request", side_effect=requests.ConnectionError("down")),
        pytest.raises(WorldModelClientUnreachable),
    ):
        WorldModelClient().simulate(build_request())


def test_health_check_ok() -> None:
    """A 200 health response returns True."""
    with patch("requests.Session.get", return_value=response_mock(200)):
        assert WorldModelClient().health_check() is True


def test_health_check_fails() -> None:
    """A non-200 health response returns False."""
    with patch("requests.Session.get", return_value=response_mock(503)):
        assert WorldModelClient().health_check() is False
