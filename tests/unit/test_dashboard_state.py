"""Tests for dashboard shared state helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from dashboards import state as state_module
from dashboards.api_client import SimulationResponse, SimulationStepResult


def build_response(results: list[SimulationStepResult]) -> SimulationResponse:
    """Build a minimal typed simulation response for tests."""
    return SimulationResponse(
        status="ok",
        hospital_id="hosp-001",
        service_id="urg-001",
        model_version="rssm-test",
        results=results,
    )


def test_get_state_initializes_empty_when_missing() -> None:
    """get_state creates an empty TabState when session state is missing."""
    fake_st = SimpleNamespace(session_state={})
    with patch.object(state_module, "st", fake_st):
        state = state_module.get_state()
    assert state.history_siips == []
    assert state.latest_response is None


def test_update_state_merges_fields() -> None:
    """update_state merges provided fields into the existing TabState."""
    fake_st = SimpleNamespace(session_state={})
    with patch.object(state_module, "st", fake_st):
        state_module.update_state(history_siips=[1.0, 2.0])
        state = state_module.get_state()
    assert state.history_siips == [1.0, 2.0]
    assert state.last_refreshed_at is not None


def test_derive_synthesis_with_response() -> None:
    """derive_synthesis identifies the peak and critical count."""
    response = build_response(
        [
            SimulationStepResult(
                step_index=0,
                predicted_siips=700.0,
                lower_bound=650.0,
                upper_bound=750.0,
                reward=0.0,
                is_critical=False,
            ),
            SimulationStepResult(
                step_index=1,
                predicted_siips=900.0,
                lower_bound=820.0,
                upper_bound=980.0,
                reward=-1.0,
                is_critical=True,
            ),
            SimulationStepResult(
                step_index=2,
                predicted_siips=850.0,
                lower_bound=800.0,
                upper_bound=920.0,
                reward=-0.5,
                is_critical=True,
            ),
        ]
    )
    synthesis = state_module.derive_synthesis(response)
    assert synthesis["peak_value"] == 900.0
    assert synthesis["peak_time_hours"] == 1
    assert synthesis["critical_count"] == 2
    assert synthesis["peak_step"].predicted_siips == 900.0


def test_derive_synthesis_with_empty_results() -> None:
    """Empty responses return sensible neutral defaults."""
    synthesis = state_module.derive_synthesis(build_response([]))
    assert synthesis["peak_value"] == 0.0
    assert synthesis["critical_count"] == 0
    assert synthesis["peak_step"] is None
