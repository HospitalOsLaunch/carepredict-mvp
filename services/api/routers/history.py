"""Canonical feature-history endpoint for v2 forecasting."""

from __future__ import annotations

from datetime import UTC, datetime
from functools import partial
from typing import Annotated
from uuid import uuid4

import anyio
import psycopg
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from services.api.dependencies.feature_window_fetcher import (
    FeatureWindowNotFoundError,
    TimescaleFeatureWindowFetcher,
)
from services.api.routers.forecast import V2ForecastServiceDep
from services.api.schemas.forecast import FORECAST_HISTORY_LENGTH
from services.api.schemas.history import FeatureWindowResponse

LOGGER = structlog.get_logger(__name__)
router = APIRouter(prefix="/history", tags=["history"])


def get_feature_window_fetcher(request: Request) -> TimescaleFeatureWindowFetcher:
    """Return the application-scoped canonical feature-window fetcher."""
    fetcher = getattr(request.app.state, "feature_window_fetcher", None)
    if isinstance(fetcher, TimescaleFeatureWindowFetcher):
        return fetcher
    fetcher = TimescaleFeatureWindowFetcher()
    request.app.state.feature_window_fetcher = fetcher
    return fetcher


FeatureWindowFetcherDep = Annotated[
    TimescaleFeatureWindowFetcher,
    Depends(get_feature_window_fetcher),
]


@router.get("/feature-window", response_model=FeatureWindowResponse)
async def feature_window(
    request: Request,
    service: V2ForecastServiceDep,
    fetcher: FeatureWindowFetcherDep,
    hospital_id: Annotated[str, Query(pattern=r"^[a-z0-9-]+$")],
    service_id: Annotated[str, Query(pattern=r"^[a-z0-9-]+$")],
    origin_timestamp: Annotated[str, Query()],
    length: Annotated[int, Query(ge=1, le=FORECAST_HISTORY_LENGTH)] = FORECAST_HISTORY_LENGTH,
) -> FeatureWindowResponse:
    """Return a canonical 7-channel feature window aligned to the v2 forecast head."""
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    LOGGER.info(
        "feature_window_requested",
        hospital_id=hospital_id,
        service_id=service_id,
        origin_timestamp=origin_timestamp,
        length=length,
        request_id=request_id,
    )
    try:
        origin = _parse_origin(origin_timestamp)
        fetch_call = partial(
            fetcher.fetch,
            hospital_id=hospital_id,
            service_id=service_id,
            origin_timestamp=origin,
            length=length,
            artifacts=service.artifacts,
        )
        window = await anyio.to_thread.run_sync(fetch_call)
    except FeatureWindowNotFoundError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        LOGGER.warning("feature_window_artifact_missing", request_id=request_id, error=str(exc))
        raise HTTPException(
            status_code=503,
            detail="V2 forecast artifacts are not available",
        ) from exc
    except psycopg.Error as exc:
        LOGGER.warning("feature_window_db_unavailable", request_id=request_id, error=str(exc))
        raise HTTPException(status_code=503, detail="TimescaleDB is not available") from exc
    except Exception as exc:
        LOGGER.exception(
            "feature_window_failed",
            request_id=request_id,
            hospital_id=hospital_id,
            service_id=service_id,
        )
        raise HTTPException(status_code=500, detail="Feature window fetch failed") from exc

    return FeatureWindowResponse(
        service_id=window.service_id,
        hospital_id=window.hospital_id,
        origin_timestamp=window.origin_timestamp,
        length=window.length,
        channels=window.channels,
        history=window.history,
    )


def _parse_origin(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
