"""Pydantic schemas for operational action recommendations."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

ActionLever = Literal[
    "move_staff",
    "open_beds",
    "close_beds",
    "prioritize_discharge",
    "rebalance_workload",
]
ActionSeverity = Literal["critical", "high", "elevated", "normal"]
ActionStatus = Literal["proposed", "approved", "in_progress", "done", "dismissed"]


class ActionRecommendRequest(BaseModel):
    """Request body for ``POST /actions/recommend``."""

    model_config = ConfigDict(extra="forbid")

    facility_id: Annotated[str, Field(pattern=r"^[a-z0-9-]+$")]
    horizon_h: Annotated[int, Field(ge=1, le=48)]
    services: Annotated[list[str], Field(min_length=1, max_length=10)]
    origin: datetime


class RiskWindow(BaseModel):
    """Forecast window during which at-risk services exceed their threshold."""

    model_config = ConfigDict(extra="forbid")

    start: datetime | None
    end: datetime | None


class OpportunityKPIs(BaseModel):
    """Aggregated opportunity metrics derived from ranked recommendations."""

    model_config = ConfigDict(extra="forbid")

    total_projected_impact_siips: float
    critical_actions_count: int
    services_at_risk: int
    risk_window: RiskWindow


class Recommendation(BaseModel):
    """One proposed operational action."""

    model_config = ConfigDict(extra="forbid")

    id: str
    service_id: str
    lever: ActionLever
    title: str
    severity: ActionSeverity
    score: Annotated[float, Field(ge=0.0, le=1.0)]
    projected_impact_siips: float
    feasibility: Annotated[float, Field(ge=0.0, le=1.0)]
    rationale: str
    horizon_h: int
    status: ActionStatus = "proposed"


class ActionRecommendResponse(BaseModel):
    """Response body for ranked recommendation opportunities."""

    model_config = ConfigDict(extra="forbid")

    opportunity: OpportunityKPIs
    recommendations: list[Recommendation]


class ActionTransitionRequest(BaseModel):
    """Request body for a traced decision-state transition."""

    model_config = ConfigDict(extra="forbid")

    to_status: ActionStatus
    actor: Annotated[str, Field(min_length=1, max_length=120)]
    reason: Annotated[str | None, Field(max_length=500)] = None


class ActionEvent(BaseModel):
    """One immutable Action Engine audit event."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    recommendation_id: str
    from_status: ActionStatus | None
    to_status: ActionStatus
    actor: str
    reason: str | None
    occurred_at: datetime


class StoredRecommendation(BaseModel):
    """Persisted recommendation state."""

    model_config = ConfigDict(extra="forbid")

    recommendation_id: str
    hospital_id: str
    service_id: str
    lever: ActionLever
    severity: ActionSeverity
    score: float
    projected_impact_siips: float
    status: ActionStatus
    created_at: datetime
    updated_at: datetime


class ActionTransitionResponse(BaseModel):
    """Transition response containing updated state and appended audit event."""

    model_config = ConfigDict(extra="forbid")

    recommendation: StoredRecommendation
    event: ActionEvent


class ActionEventsResponse(BaseModel):
    """Ordered audit trail response."""

    model_config = ConfigDict(extra="forbid")

    recommendation_id: str
    events: list[ActionEvent]
