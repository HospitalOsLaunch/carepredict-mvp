"""Tests for Gate B action counterfactual simulation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.recommend.simulate_mapping import (
    PRIORITIZE_DISCHARGE_TOTAL,
    action_plan_for_lever,
)
from services.api.routers.actions import get_siips_history_fetcher, router
from services.api.routers.simulate import get_world_model_service


@dataclass(frozen=True, slots=True)
class FakeConfig:
    max_history_length: int = 48


class DirectionalWorldModel:
    """World model fixture whose supported actions reduce future peaks."""

    config = FakeConfig()

    def simulate(
        self,
        history_siips: list[float],
        action_sequence: list[list[float]],
    ) -> list[dict[str, float | int | bool]]:
        baseline = float(history_siips[-1])
        rows: list[dict[str, float | int | bool]] = []
        cumulative_effect = 0.0
        for index, action in enumerate(action_sequence):
            _admissions, discharges, redeployments, _surgeries, _transfers = action
            cumulative_effect += discharges * 18.0 + redeployments * 11.0
            predicted = baseline + 80.0 - index * 0.5 - cumulative_effect
            rows.append(
                {
                    "step_index": index,
                    "predicted_siips": predicted,
                    "lower_bound": predicted - 40.0,
                    "upper_bound": predicted + 50.0,
                    "reward": 0.0,
                    "is_critical": predicted >= 900.0,
                }
            )
        return rows


class FakeSiipsHistoryFetcher:
    """Return a valid SIIPS history without touching TimescaleDB."""

    def fetch(
        self,
        *,
        hospital_id: str,
        service_id: str,
        origin: datetime,
        length: int,
    ) -> list[float]:
        assert hospital_id == "hosp-001"
        assert service_id == "urg-001"
        assert origin == datetime(2025, 9, 10, tzinfo=UTC)
        return [820.0 + index for index in range(length)]


def test_action_plan_uses_realistic_total_magnitudes() -> None:
    discharge_plan = action_plan_for_lever("prioritize_discharge", 48)
    staff_plan = action_plan_for_lever("move_staff", 48)

    assert discharge_plan.mode == "counterfactual"
    assert sum(step.scheduled_discharges for step in discharge_plan.actions) == PRIORITIZE_DISCHARGE_TOTAL
    assert staff_plan.mode == "heuristic"
    assert staff_plan.actions == []


def test_prioritize_discharge_counterfactual_reduces_peak() -> None:
    payload = _simulate_payload("prioritize_discharge")
    response = _client().post("/actions/rec_discharge/simulate", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "counterfactual"
    assert body["summary"]["peak_after"] < body["summary"]["peak_before"]
    assert body["summary"]["delta_siips"] < 0.0


def test_move_staff_is_demoted_to_heuristic_after_direction_guard() -> None:
    payload = _simulate_payload("move_staff")
    response = _client().post("/actions/rec_staff/simulate", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "heuristic"
    assert body["baseline"] == []
    assert body["after"] == []


def test_heuristic_lever_returns_explicit_heuristic_mode() -> None:
    payload = _simulate_payload("open_beds")
    payload["projected_impact_siips"] = -12.5
    response = _client().post("/actions/rec_beds/simulate", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "heuristic"
    assert body["baseline"] == []
    assert body["after"] == []
    assert body["summary"]["delta_siips"] == -12.5


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_world_model_service] = lambda: DirectionalWorldModel()
    app.dependency_overrides[get_siips_history_fetcher] = lambda: FakeSiipsHistoryFetcher()
    return TestClient(app)


def _simulate_payload(lever: str) -> dict[str, object]:
    return {
        "facility_id": "hosp-001",
        "service_id": "urg-001",
        "lever": lever,
        "origin": "2025-09-10T00:00:00Z",
        "horizon_h": 48,
        "projected_impact_siips": -18.0,
    }
