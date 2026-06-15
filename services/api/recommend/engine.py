"""Recommendation orchestration for ``POST /actions/recommend``."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Protocol

from services.api.dependencies.feature_window_fetcher import TimescaleFeatureWindowFetcher
from services.api.recommend.levers import candidate_levers
from services.api.recommend.scoring import ForecastContext, ForecastPoint, RuleBasedScorer, ScoredAction
from services.api.recommend.thresholds import (
    ForecastP75ThresholdProvider,
    ServiceThresholdProvider,
)
from services.api.schemas.actions import OpportunityKPIs, Recommendation, RiskWindow
from services.ml.forecasting.v2_service import V2ForecastService


class ForecastServiceLike(Protocol):
    """Subset of ``V2ForecastService`` required by the engine."""

    artifacts: object

    def forecast(
        self,
        *,
        history: list[list[float]],
        origin_timestamp: datetime,
        horizon: int,
    ) -> list[dict[str, float | int]]:
        """Return raw forecast dictionaries."""


class FeatureWindowFetcherLike(Protocol):
    """Subset of ``TimescaleFeatureWindowFetcher`` required by the engine."""

    def fetch(
        self,
        *,
        hospital_id: str,
        service_id: str,
        origin_timestamp: datetime,
        length: int,
        artifacts: object,
    ) -> object:
        """Return an object with a ``history`` attribute."""


@dataclass(frozen=True, slots=True)
class RecommendationResult:
    """Recommendation engine result."""

    opportunity: OpportunityKPIs
    recommendations: list[Recommendation]


class RecommendationEngine:
    """Fan-out forecasts, detect service risk, score candidate levers and rank actions."""

    def __init__(
        self,
        *,
        forecast_service: ForecastServiceLike,
        feature_fetcher: FeatureWindowFetcherLike | None = None,
        scorer: RuleBasedScorer | None = None,
        threshold_provider: ServiceThresholdProvider | None = None,
        history_length: int | None = None,
    ) -> None:
        self.forecast_service = forecast_service
        self.feature_fetcher = feature_fetcher or TimescaleFeatureWindowFetcher()
        self.scorer = scorer or RuleBasedScorer()
        self.threshold_provider = threshold_provider or ForecastP75ThresholdProvider(
            forecast_service=forecast_service,
            feature_fetcher=self.feature_fetcher,
        )
        self.history_length = history_length or getattr(forecast_service, "history_length", 120)

    def recommend(
        self,
        *,
        facility_id: str,
        services: list[str],
        origin: datetime,
        horizon_h: int,
    ) -> RecommendationResult:
        """Return ranked recommendations for at-risk services."""
        scored: list[ScoredAction] = []
        contexts: list[ForecastContext] = []
        for service_id in services:
            window = self.feature_fetcher.fetch(
                hospital_id=facility_id,
                service_id=service_id,
                origin_timestamp=origin,
                length=self.history_length,
                artifacts=self.forecast_service.artifacts,
            )
            raw_forecast = self.forecast_service.forecast(
                history=window.history,
                origin_timestamp=origin,
                horizon=horizon_h,
            )
            threshold = self.threshold_provider.threshold_for(
                hospital_id=facility_id,
                service_id=service_id,
            )
            ctx = forecast_context(
                service_id=service_id,
                horizon_h=horizon_h,
                threshold=threshold,
                raw_forecast=raw_forecast,
            )
            if ctx.hours_above_threshold <= 0:
                continue
            contexts.append(ctx)
            for candidate in candidate_levers(service_id):
                scored.append(self.scorer.score(candidate, ctx))

        ranked = sorted(scored, key=lambda action: action.score, reverse=True)
        recommendations = [Recommendation(**asdict(action)) for action in ranked]
        return RecommendationResult(
            opportunity=opportunity_from_actions(
                actions=recommendations,
                contexts=contexts,
                origin=origin,
            ),
            recommendations=recommendations,
        )


def forecast_context(
    *,
    service_id: str,
    horizon_h: int,
    threshold: float,
    raw_forecast: list[dict[str, float | int]],
) -> ForecastContext:
    """Convert raw forecast dictionaries into a risk context."""
    points = tuple(
        ForecastPoint(
            step_index=int(item["step_index"]),
            predicted_siips=float(item["predicted_siips"]),
            lower_90=float(item["lower_90"]),
            upper_90=float(item["upper_90"]),
        )
        for item in raw_forecast
    )
    if not points:
        return ForecastContext(service_id, horizon_h, threshold, 0.0, 0, 0, 0.0, ())
    peak = max(points, key=lambda point: point.predicted_siips)
    excesses = [max(point.predicted_siips - threshold, 0.0) for point in points]
    return ForecastContext(
        service_id=service_id,
        horizon_h=horizon_h,
        threshold=threshold,
        peak_siips=peak.predicted_siips,
        peak_step=peak.step_index,
        hours_above_threshold=sum(1 for value in excesses if value > 0.0),
        total_excess_siips=sum(excesses),
        forecast=points,
    )


def opportunity_from_actions(
    *,
    actions: list[Recommendation],
    contexts: list[ForecastContext],
    origin: datetime,
) -> OpportunityKPIs:
    """Aggregate opportunity KPIs from ranked recommendations and risk contexts."""
    critical_count = sum(1 for action in actions if action.severity == "critical")
    risk_steps = [
        point.step_index
        for context in contexts
        for point in context.forecast
        if point.predicted_siips > context.threshold
    ]
    if risk_steps:
        start = origin + timedelta(hours=min(risk_steps))
        end = origin + timedelta(hours=max(risk_steps))
    else:
        start = None
        end = None
    return OpportunityKPIs(
        total_projected_impact_siips=round(
            sum(abs(action.projected_impact_siips) for action in actions),
            2,
        ),
        critical_actions_count=critical_count,
        services_at_risk=len({context.service_id for context in contexts}),
        risk_window=RiskWindow(start=start, end=end),
    )


def build_recommendation_engine(service: V2ForecastService) -> RecommendationEngine:
    """Build the default Gate A recommendation engine for FastAPI serving."""
    return RecommendationEngine(forecast_service=service)
