"""Unit tests for the Gate A recommendation engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.recommend.engine import RecommendationEngine
from services.api.routers.actions import get_recommendation_engine, router


@dataclass(frozen=True, slots=True)
class FakeWindow:
    """Feature-window fixture."""

    history: list[list[float]]


class FakeForecastService:
    """Forecast service fixture."""

    artifacts = object()
    history_length = 120

    def forecast(
        self,
        *,
        history: list[list[float]],
        origin_timestamp: datetime,
        horizon: int,
    ) -> list[dict[str, float | int]]:
        service_code = int(history[0][0])
        if service_code == 1:
            values = [1500.0, 1620.0, 1710.0, 1680.0, 1450.0, 1400.0]
        elif service_code == 2:
            values = [1200.0, 1190.0, 1180.0, 1170.0, 1160.0, 1150.0]
        else:
            values = [1800.0, 1825.0, 1790.0, 1785.0, 1705.0, 1690.0]
        return [
            {
                "step_index": index + 1,
                "predicted_siips": values[index % len(values)],
                "lower_90": values[index % len(values)] - 50.0,
                "upper_90": values[index % len(values)] + 60.0,
            }
            for index in range(horizon)
        ]


class FakeFetcher:
    """Feature-window fetcher fixture encoding service identity in the first value."""

    def fetch(
        self,
        *,
        hospital_id: str,
        service_id: str,
        origin_timestamp: datetime,
        length: int,
        artifacts: object,
    ) -> FakeWindow:
        code = {"urg-001": 1.0, "med-001": 2.0, "rea-001": 3.0}[service_id]
        return FakeWindow(history=[[code, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0] for _ in range(length)])


def test_engine_scores_only_at_risk_services_and_ranks_actions() -> None:
    engine = RecommendationEngine(
        forecast_service=FakeForecastService(),
        feature_fetcher=FakeFetcher(),
        threshold=1600.0,
    )

    result = engine.recommend(
        facility_id="hosp-001",
        services=["urg-001", "med-001", "rea-001"],
        origin=datetime(2025, 7, 8, tzinfo=UTC),
        horizon_h=6,
    )

    assert result.opportunity.services_at_risk == 2
    assert result.opportunity.critical_actions_count > 0
    assert result.opportunity.total_projected_impact_siips > 0.0
    assert result.opportunity.risk_window.start == datetime(2025, 7, 8, 1, tzinfo=UTC)
    assert result.recommendations
    assert all(action.service_id != "med-001" for action in result.recommendations)
    assert result.recommendations == sorted(
        result.recommendations,
        key=lambda action: action.score,
        reverse=True,
    )


def test_engine_returns_empty_opportunity_without_risk() -> None:
    engine = RecommendationEngine(
        forecast_service=FakeForecastService(),
        feature_fetcher=FakeFetcher(),
        threshold=2000.0,
    )

    result = engine.recommend(
        facility_id="hosp-001",
        services=["urg-001", "med-001"],
        origin=datetime(2025, 7, 8, tzinfo=UTC),
        horizon_h=6,
    )

    assert result.recommendations == []
    assert result.opportunity.services_at_risk == 0
    assert result.opportunity.total_projected_impact_siips == 0.0
    assert result.opportunity.risk_window.start is None
    assert result.opportunity.risk_window.end is None


def test_actions_recommend_route_contract() -> None:
    engine = RecommendationEngine(
        forecast_service=FakeForecastService(),
        feature_fetcher=FakeFetcher(),
        threshold=1600.0,
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_recommendation_engine] = lambda: engine

    with TestClient(app) as client:
        response = client.post(
            "/actions/recommend",
            json={
                "facility_id": "hosp-001",
                "horizon_h": 6,
                "services": ["urg-001", "med-001"],
                "origin": "2025-07-08T00:00:00Z",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["opportunity"]["services_at_risk"] == 1
    assert payload["recommendations"]
    assert payload["recommendations"][0]["status"] == "proposed"
