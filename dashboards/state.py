"""Shared typed session state for Hospitalos dashboard tabs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st
from pydantic import BaseModel, Field

from dashboards.api_client import SimulationResponse, SimulationStepResult

STATE_KEY = "hospitalos_tab_state"


class TabState(BaseModel):
    """Shared state across dashboard tabs."""

    history_siips: list[float] = Field(default_factory=list)
    latest_response: SimulationResponse | None = None
    compare_baseline: SimulationResponse | None = None
    compare_intervention: SimulationResponse | None = None
    last_refreshed_at: str | None = None


def get_state() -> TabState:
    """Read TabState from Streamlit session state, creating one if missing."""
    raw_state = st.session_state.get(STATE_KEY)
    if isinstance(raw_state, TabState):
        return raw_state
    state = TabState.model_validate(raw_state) if isinstance(raw_state, dict) else TabState()
    st.session_state[STATE_KEY] = state
    return state


def update_state(**kwargs: Any) -> None:
    """Update selected fields of the shared TabState in session state."""
    state = get_state()
    payload = state.model_dump()
    payload.update(kwargs)
    if "last_refreshed_at" not in kwargs:
        payload["last_refreshed_at"] = datetime.now().isoformat(timespec="seconds")
    st.session_state[STATE_KEY] = TabState.model_validate(payload)


def derive_synthesis(
    response: SimulationResponse,
    critical_threshold: float = 850.0,
) -> dict[str, object]:
    """Compute peak and criticality facts from a simulation response."""
    if not response.results:
        return {
            "peak_step": None,
            "peak_time_hours": 0,
            "peak_value": 0.0,
            "peak_ci": (0.0, 0.0),
            "critical_count": 0,
            "max_value": 0.0,
            "critical_threshold": critical_threshold,
        }
    peak_step = max(response.results, key=lambda step: step.predicted_siips)
    critical_count = sum(1 for step in response.results if step.is_critical)
    return {
        "peak_step": peak_step,
        "peak_time_hours": int(peak_step.step_index),
        "peak_value": float(peak_step.predicted_siips),
        "peak_ci": (float(peak_step.lower_bound), float(peak_step.upper_bound)),
        "critical_count": int(critical_count),
        "max_value": float(peak_step.predicted_siips),
        "critical_threshold": critical_threshold,
    }


def coerce_step(value: object) -> SimulationStepResult | None:
    """Return a typed simulation step when a synthesis peak is present."""
    if isinstance(value, SimulationStepResult):
        return value
    return None
