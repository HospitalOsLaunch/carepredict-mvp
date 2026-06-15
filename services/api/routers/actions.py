"""Operational recommendation endpoint."""

from __future__ import annotations

from functools import partial
from typing import Annotated
from uuid import uuid4

import anyio
import psycopg
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import ValidationError

from services.api.recommend.engine import RecommendationEngine, build_recommendation_engine
from services.api.routers.forecast import V2ForecastServiceDep
from services.api.schemas.actions import ActionRecommendRequest, ActionRecommendResponse

LOGGER = structlog.get_logger(__name__)
router = APIRouter(prefix="/actions", tags=["actions"])
RequestIdHeader = Annotated[str | None, Header(alias="X-Request-ID")]


def get_recommendation_engine(request: Request, service: V2ForecastServiceDep) -> RecommendationEngine:
    """Return the app-scoped recommendation engine for the loaded v2 service."""
    engine = getattr(request.app.state, "recommendation_engine", None)
    if isinstance(engine, RecommendationEngine) and engine.forecast_service is service:
        return engine
    engine = build_recommendation_engine(service)
    request.app.state.recommendation_engine = engine
    return engine


RecommendationEngineDep = Annotated[RecommendationEngine, Depends(get_recommendation_engine)]


@router.post("/recommend", response_model=ActionRecommendResponse)
async def recommend_actions(
    payload: ActionRecommendRequest,
    engine: RecommendationEngineDep,
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
        recommendations=result.recommendations,
    )
