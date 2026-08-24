"""Operational recommendation endpoint."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import Annotated, Any, Protocol
from uuid import uuid4

import anyio
import psycopg
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from services.api.dependencies.feature_fetcher import DB_DSN
from services.api.recommend.engine import RecommendationEngine, build_recommendation_engine
from services.api.recommend.simulate_mapping import action_plan_for_lever, zero_action_steps
from services.api.recommend.state_machine import InvalidActionTransition, validate_transition
from services.api.routers.forecast import V2ForecastServiceDep
from services.api.routers.simulate import WorldModelServiceDep
from services.api.schemas.actions import (
    ActionEvent,
    ActionEventsResponse,
    ActionLever,
    ActionRecommendRequest,
    ActionRecommendResponse,
    ActionStatus,
    ActionTransitionRequest,
    ActionTransitionResponse,
    Recommendation,
    StoredRecommendation,
)
from services.api.schemas.simulate import ActionStep

LOGGER = structlog.get_logger(__name__)
router = APIRouter(prefix="/actions", tags=["actions"])
RequestIdHeader = Annotated[str | None, Header(alias="X-Request-ID")]


class WorldModelLike(Protocol):
    """Simulation contract required by the action endpoint."""

    def simulate(
        self, history_siips: list[float], action_sequence: list[list[float]]
    ) -> list[dict[str, float | int | bool]]:
        """Simulate one counterfactual action sequence."""


def get_recommendation_engine(
    request: Request,
    service: V2ForecastServiceDep,
) -> RecommendationEngine:
    """Return the app-scoped recommendation engine for the loaded v2 service."""
    engine = getattr(request.app.state, "recommendation_engine", None)
    if isinstance(engine, RecommendationEngine) and engine.forecast_service is service:
        return engine
    engine = build_recommendation_engine(service)
    request.app.state.recommendation_engine = engine
    return engine


RecommendationEngineDep = Annotated[RecommendationEngine, Depends(get_recommendation_engine)]


class ActionSimulateRequest(BaseModel):
    """Request a Gate B simulation for one proposed recommendation."""

    model_config = ConfigDict(extra="forbid")

    facility_id: Annotated[str, Field(pattern=r"^[a-z0-9-]+$")]
    service_id: Annotated[str, Field(pattern=r"^[a-z0-9-]+$")]
    lever: ActionLever
    origin: datetime
    horizon_h: Annotated[int, Field(ge=1, le=48)] = 48
    projected_impact_siips: float | None = None


class ActionTrajectoryStep(BaseModel):
    """One trajectory point in an action simulation."""

    model_config = ConfigDict(extra="forbid")

    step_index: int
    predicted_siips: float
    lower_bound: float
    upper_bound: float
    is_critical: bool


class ActionSimulationSummary(BaseModel):
    """Peak and delta summary for an action simulation."""

    model_config = ConfigDict(extra="forbid")

    peak_before: float | None
    peak_after: float | None
    delta_siips: float
    rationale: str


class ActionSimulationDelta(BaseModel):
    """Gate B action simulation response."""

    model_config = ConfigDict(extra="forbid")

    mode: str
    recommendation_id: str
    service_id: str
    lever: ActionLever
    baseline: list[ActionTrajectoryStep]
    after: list[ActionTrajectoryStep]
    summary: ActionSimulationSummary


@dataclass(frozen=True, slots=True)
class SiipsHistoryFetcher:
    """Read-only canonical SIIPS history fetcher for world-model simulation."""

    def fetch(
        self,
        *,
        hospital_id: str,
        service_id: str,
        origin: datetime,
        length: int,
    ) -> list[float]:
        """Fetch the hourly SIIPS history ending immediately before ``origin``."""
        origin_utc = _to_utc(origin)
        with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.siips_score
                FROM canonical.care_load c
                WHERE c.hospital_id = %s
                  AND c.service_id = %s
                  AND c.measured_at < %s
                ORDER BY c.measured_at DESC
                LIMIT %s
                """,
                (hospital_id, service_id, origin_utc, length),
            )
            rows = cur.fetchall()
        if len(rows) < length:
            raise ValueError(
                f"insufficient SIIPS history before {origin_utc.isoformat()} "
                f"for {hospital_id}/{service_id}: expected {length}, got {len(rows)}"
            )
        return [float(row[0]) for row in reversed(rows)]


def get_siips_history_fetcher(request: Request) -> SiipsHistoryFetcher:
    """Return the app-scoped SIIPS history fetcher."""
    fetcher = getattr(request.app.state, "siips_history_fetcher", None)
    if isinstance(fetcher, SiipsHistoryFetcher):
        return fetcher
    fetcher = SiipsHistoryFetcher()
    request.app.state.siips_history_fetcher = fetcher
    return fetcher


SiipsHistoryFetcherDep = Annotated[SiipsHistoryFetcher, Depends(get_siips_history_fetcher)]


class ActionNotFoundError(ValueError):
    """Raised when a persisted recommendation cannot be found."""


@dataclass(frozen=True, slots=True)
class ActionStore:
    """Transactional store for recommendation state and immutable audit events."""

    def persist_recommendations(
        self,
        *,
        hospital_id: str,
        recommendations: list[Recommendation],
    ) -> dict[str, ActionStatus]:
        """Persist current recommendation rows without resetting workflow status."""
        with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
            for recommendation in recommendations:
                cur.execute(
                    """
                    INSERT INTO actions.recommendations (
                        recommendation_id,
                        hospital_id,
                        service_id,
                        lever,
                        severity,
                        score,
                        projected_impact_siips,
                        status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'proposed')
                    ON CONFLICT (recommendation_id) DO NOTHING
                    """,
                    (
                        recommendation.id,
                        hospital_id,
                        recommendation.service_id,
                        recommendation.lever,
                        recommendation.severity,
                        recommendation.score,
                        recommendation.projected_impact_siips,
                    ),
                )
                inserted = cur.rowcount == 1
                if inserted:
                    cur.execute(
                        """
                        INSERT INTO actions.action_events (
                            recommendation_id,
                            from_status,
                            to_status,
                            actor,
                            reason
                        )
                        VALUES (%s, NULL, 'proposed', 'system', 'recommendation created')
                        """,
                        (recommendation.id,),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE actions.recommendations
                        SET hospital_id = %s,
                            service_id = %s,
                            lever = %s,
                            severity = %s,
                            score = %s,
                            projected_impact_siips = %s,
                            updated_at = now()
                        WHERE recommendation_id = %s
                        """,
                        (
                            hospital_id,
                            recommendation.service_id,
                            recommendation.lever,
                            recommendation.severity,
                            recommendation.score,
                            recommendation.projected_impact_siips,
                            recommendation.id,
                        ),
                    )
            if not recommendations:
                return {}
            cur.execute(
                """
                SELECT recommendation_id, status
                FROM actions.recommendations
                WHERE recommendation_id = ANY(%s)
                """,
                ([recommendation.id for recommendation in recommendations],),
            )
            return {str(row[0]): row[1] for row in cur.fetchall()}

    def transition(
        self,
        *,
        recommendation_id: str,
        to_status: str,
        actor: str,
        reason: str | None,
    ) -> ActionTransitionResponse:
        """Atomically update current state and append one audit event."""
        with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT status
                FROM actions.recommendations
                WHERE recommendation_id = %s
                FOR UPDATE
                """,
                (recommendation_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ActionNotFoundError(f"unknown recommendation_id: {recommendation_id}")
            from_status = str(row[0])
            validate_transition(from_status, to_status)  # type: ignore[arg-type]
            cur.execute(
                """
                UPDATE actions.recommendations
                SET status = %s,
                    updated_at = now()
                WHERE recommendation_id = %s
                RETURNING
                    recommendation_id,
                    hospital_id,
                    service_id,
                    lever,
                    severity,
                    score::float,
                    projected_impact_siips::float,
                    status,
                    created_at,
                    updated_at
                """,
                (to_status, recommendation_id),
            )
            recommendation_row = cur.fetchone()
            cur.execute(
                """
                INSERT INTO actions.action_events (
                    recommendation_id,
                    from_status,
                    to_status,
                    actor,
                    reason
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING
                    event_id::text,
                    recommendation_id,
                    from_status,
                    to_status,
                    actor,
                    reason,
                    occurred_at
                """,
                (recommendation_id, from_status, to_status, actor, reason),
            )
            event_row = cur.fetchone()
        return ActionTransitionResponse(
            recommendation=_stored_recommendation_from_row(recommendation_row),
            event=_event_from_row(event_row),
        )

    def events(self, *, recommendation_id: str) -> list[ActionEvent]:
        """Return ordered audit events for one recommendation."""
        with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM actions.recommendations
                WHERE recommendation_id = %s
                """,
                (recommendation_id,),
            )
            if cur.fetchone() is None:
                raise ActionNotFoundError(f"unknown recommendation_id: {recommendation_id}")
            cur.execute(
                """
                SELECT
                    event_id::text,
                    recommendation_id,
                    from_status,
                    to_status,
                    actor,
                    reason,
                    occurred_at
                FROM actions.action_events
                WHERE recommendation_id = %s
                ORDER BY occurred_at ASC, event_id ASC
                """,
                (recommendation_id,),
            )
            return [_event_from_row(row) for row in cur.fetchall()]


def get_action_store(request: Request) -> ActionStore:
    """Return the app-scoped Action Engine store."""
    store = getattr(request.app.state, "action_store", None)
    if isinstance(store, ActionStore):
        return store
    store = ActionStore()
    request.app.state.action_store = store
    return store


ActionStoreDep = Annotated[ActionStore, Depends(get_action_store)]


@router.post("/recommend", response_model=ActionRecommendResponse)
async def recommend_actions(
    payload: ActionRecommendRequest,
    engine: RecommendationEngineDep,
    store: ActionStoreDep,
    x_request_id: RequestIdHeader = None,
) -> ActionRecommendResponse:
    """Return ranked operational action opportunities."""
    request_id = x_request_id or str(uuid4())
    LOGGER.info(
        "actions_recommend_requested",
        facility_id=payload.facility_id,
        services=payload.services,
        horizon_h=payload.horizon_h,
        request_id=request_id,
    )
    try:
        recommend_call = partial(
            engine.recommend,
            facility_id=payload.facility_id,
            services=payload.services,
            origin=payload.origin,
            horizon_h=payload.horizon_h,
        )
        result = await anyio.to_thread.run_sync(recommend_call)
        persist_call = partial(
            store.persist_recommendations,
            hospital_id=payload.facility_id,
            recommendations=result.recommendations,
        )
        statuses = await anyio.to_thread.run_sync(persist_call)
        recommendations = [
            recommendation.model_copy(
                update={"status": statuses.get(recommendation.id, recommendation.status)}
            )
            for recommendation in result.recommendations
        ]
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        LOGGER.warning("actions_recommend_artifact_missing", request_id=request_id, error=str(exc))
        raise HTTPException(
            status_code=503,
            detail="Recommendation artifacts are not available",
        ) from exc
    except psycopg.Error as exc:
        LOGGER.warning("actions_recommend_db_unavailable", request_id=request_id, error=str(exc))
        raise HTTPException(status_code=503, detail="TimescaleDB is not available") from exc
    except Exception as exc:
        LOGGER.exception("actions_recommend_failed", request_id=request_id)
        raise HTTPException(status_code=500, detail="Action recommendation failed") from exc

    return ActionRecommendResponse(
        opportunity=result.opportunity,
        recommendations=recommendations,
    )


@router.post("/{recommendation_id}/transition", response_model=ActionTransitionResponse)
async def transition_action(
    recommendation_id: str,
    payload: ActionTransitionRequest,
    store: ActionStoreDep,
    x_request_id: RequestIdHeader = None,
) -> ActionTransitionResponse:
    """Trace a decision workflow transition; this does not execute hospital work."""
    request_id = x_request_id or str(uuid4())
    LOGGER.info(
        "actions_transition_requested",
        recommendation_id=recommendation_id,
        to_status=payload.to_status,
        actor=payload.actor,
        request_id=request_id,
    )
    try:
        transition_call = partial(
            store.transition,
            recommendation_id=recommendation_id,
            to_status=payload.to_status,
            actor=payload.actor,
            reason=payload.reason,
        )
        return await anyio.to_thread.run_sync(transition_call)
    except ActionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidActionTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except psycopg.Error as exc:
        LOGGER.warning("actions_transition_db_unavailable", request_id=request_id, error=str(exc))
        raise HTTPException(status_code=503, detail="TimescaleDB is not available") from exc
    except Exception as exc:
        LOGGER.exception("actions_transition_failed", request_id=request_id)
        raise HTTPException(status_code=500, detail="Action transition failed") from exc


@router.get("/{recommendation_id}/events", response_model=ActionEventsResponse)
async def get_action_events(
    recommendation_id: str,
    store: ActionStoreDep,
    x_request_id: RequestIdHeader = None,
) -> ActionEventsResponse:
    """Return the ordered immutable audit trail for one recommendation."""
    request_id = x_request_id or str(uuid4())
    try:
        events_call = partial(store.events, recommendation_id=recommendation_id)
        events = await anyio.to_thread.run_sync(events_call)
    except ActionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except psycopg.Error as exc:
        LOGGER.warning("actions_events_db_unavailable", request_id=request_id, error=str(exc))
        raise HTTPException(status_code=503, detail="TimescaleDB is not available") from exc
    except Exception as exc:
        LOGGER.exception("actions_events_failed", request_id=request_id)
        raise HTTPException(status_code=500, detail="Action events fetch failed") from exc
    return ActionEventsResponse(recommendation_id=recommendation_id, events=events)


@router.post("/{recommendation_id}/simulate", response_model=ActionSimulationDelta)
async def simulate_action_recommendation(
    recommendation_id: str,
    payload: ActionSimulateRequest,
    world_model: WorldModelServiceDep,
    history_fetcher: SiipsHistoryFetcherDep,
    x_request_id: RequestIdHeader = None,
) -> ActionSimulationDelta:
    """Simulate one recommendation against the world model when its lever is supported."""
    request_id = x_request_id or str(uuid4())
    plan = action_plan_for_lever(payload.lever, payload.horizon_h)
    LOGGER.info(
        "actions_simulate_requested",
        recommendation_id=recommendation_id,
        service_id=payload.service_id,
        lever=payload.lever,
        mode=plan.mode,
        request_id=request_id,
    )
    if plan.mode == "heuristic":
        return ActionSimulationDelta(
            mode="heuristic",
            recommendation_id=recommendation_id,
            service_id=payload.service_id,
            lever=payload.lever,
            baseline=[],
            after=[],
            summary=ActionSimulationSummary(
                peak_before=None,
                peak_after=None,
                delta_siips=float(payload.projected_impact_siips or 0.0),
                rationale=plan.rationale,
            ),
        )

    try:
        history_length = int(world_model.config.max_history_length)
        history_call = partial(
            history_fetcher.fetch,
            hospital_id=payload.facility_id,
            service_id=payload.service_id,
            origin=payload.origin,
            length=history_length,
        )
        history_siips = await anyio.to_thread.run_sync(history_call)
        baseline_actions = zero_action_steps(payload.horizon_h)
        baseline = await _simulate_trajectory(world_model, history_siips, baseline_actions)
        after = await _simulate_trajectory(world_model, history_siips, plan.actions)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        LOGGER.warning("actions_simulate_artifact_missing", request_id=request_id, error=str(exc))
        raise HTTPException(
            status_code=503,
            detail="World model artifacts are not available",
        ) from exc
    except psycopg.Error as exc:
        LOGGER.warning("actions_simulate_db_unavailable", request_id=request_id, error=str(exc))
        raise HTTPException(status_code=503, detail="TimescaleDB is not available") from exc
    except Exception as exc:
        LOGGER.exception("actions_simulate_failed", request_id=request_id)
        raise HTTPException(status_code=500, detail="Action simulation failed") from exc

    peak_before = max(step.predicted_siips for step in baseline)
    peak_after = max(step.predicted_siips for step in after)
    return ActionSimulationDelta(
        mode="counterfactual",
        recommendation_id=recommendation_id,
        service_id=payload.service_id,
        lever=payload.lever,
        baseline=baseline,
        after=after,
        summary=ActionSimulationSummary(
            peak_before=peak_before,
            peak_after=peak_after,
            delta_siips=peak_after - peak_before,
            rationale=plan.rationale,
        ),
    )


async def _simulate_trajectory(
    world_model: WorldModelLike,
    history_siips: list[float],
    actions: list[ActionStep],
) -> list[ActionTrajectoryStep]:
    action_sequence = [action.to_vector() for action in actions]
    simulate_call = partial(world_model.simulate, history_siips, action_sequence)
    raw_results = await anyio.to_thread.run_sync(simulate_call)
    return [
        ActionTrajectoryStep(
            step_index=int(item["step_index"]),
            predicted_siips=float(item["predicted_siips"]),
            lower_bound=float(item["lower_bound"]),
            upper_bound=float(item["upper_bound"]),
            is_critical=bool(item["is_critical"]),
        )
        for item in raw_results
    ]


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _stored_recommendation_from_row(row: Sequence[Any] | None) -> StoredRecommendation:
    if row is None:
        raise ActionNotFoundError("recommendation update returned no row")
    values = tuple(row)
    return StoredRecommendation(
        recommendation_id=str(values[0]),
        hospital_id=str(values[1]),
        service_id=str(values[2]),
        lever=values[3],
        severity=values[4],
        score=float(values[5]),
        projected_impact_siips=float(values[6]),
        status=values[7],
        created_at=values[8],
        updated_at=values[9],
    )


def _event_from_row(row: Sequence[Any] | None) -> ActionEvent:
    if row is None:
        raise ActionNotFoundError("action event insert returned no row")
    values = tuple(row)
    return ActionEvent(
        event_id=str(values[0]),
        recommendation_id=str(values[1]),
        from_status=values[2],
        to_status=values[3],
        actor=str(values[4]),
        reason=values[5],
        occurred_at=values[6],
    )
