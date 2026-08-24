"""Action-free v2 forecast endpoint for hospital charge."""

from __future__ import annotations

from functools import partial
from typing import Annotated
from uuid import uuid4

import anyio
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import ValidationError

from services.api.schemas.forecast import ForecastRequest, ForecastResponse, ForecastStep
from services.ml.forecasting.v2_service import V2ForecastService

LOGGER = structlog.get_logger(__name__)
router = APIRouter(prefix="/forecast", tags=["forecast"])


def get_v2_forecast_service(request: Request) -> V2ForecastService:
    """Return the application-scoped v2 forecast service."""
    service = getattr(request.app.state, "v2_forecast_service", None)
    if isinstance(service, V2ForecastService):
        return service
    try:
        service = V2ForecastService.from_artifacts()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail="V2 forecast artifacts are not available",
        ) from exc
    request.app.state.v2_forecast_service = service
    return service


V2ForecastServiceDep = Annotated[V2ForecastService, Depends(get_v2_forecast_service)]
RequestIdHeader = Annotated[str | None, Header(alias="X-Request-ID")]


@router.post("/charge", response_model=ForecastResponse)
async def forecast_charge(
    payload: ForecastRequest,
    service: V2ForecastServiceDep,
    x_request_id: RequestIdHeader = None,
) -> ForecastResponse:
    """Forecast service charge with the v2 direct forecast head."""
    request_id = x_request_id or str(uuid4())
    LOGGER.info(
        "v2_forecast_requested",
        hospital_id=payload.hospital_id,
        service_id=payload.service_id,
        history_length=len(payload.history),
        horizon=payload.horizon,
        request_id=request_id,
    )
    history = [step.to_vector() for step in payload.history]
    try:
        forecast_call = partial(
            service.forecast,
            history=history,
            origin_timestamp=payload.origin_timestamp,
            horizon=payload.horizon,
        )
        raw_results = await anyio.to_thread.run_sync(forecast_call)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        LOGGER.warning(
            "v2_forecast_artifact_missing",
            request_id=request_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=503,
            detail="V2 forecast artifacts are not available",
        ) from exc
    except Exception as exc:
        LOGGER.exception(
            "v2_forecast_failed",
            request_id=request_id,
            hospital_id=payload.hospital_id,
            service_id=payload.service_id,
        )
        raise HTTPException(status_code=500, detail="V2 forecast failed") from exc

    return ForecastResponse(
        status="ok",
        hospital_id=payload.hospital_id,
        service_id=payload.service_id,
        model_version=service.model_version,
        granularity=service.granularity,
        results=[ForecastStep.model_validate(item) for item in raw_results],
    )
