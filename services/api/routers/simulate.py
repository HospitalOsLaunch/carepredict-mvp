"""Simulation endpoint for the Hospital World Model."""

from __future__ import annotations

from functools import partial
from typing import Annotated
from uuid import uuid4

import anyio
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import ValidationError

from services.api.schemas.simulate import (
    SimulationRequest,
    SimulationResponse,
    SimulationStepResult,
)
from services.ml.world_model.inference import WorldModelService

LOGGER = structlog.get_logger(__name__)
router = APIRouter(prefix="/simulate", tags=["world-model"])


def get_world_model_service(request: Request) -> WorldModelService:
    """Return the application-scoped world model service loaded during FastAPI lifespan."""
    service = getattr(request.app.state, "world_model_service", None)
    if isinstance(service, WorldModelService):
        return service
    try:
        service = WorldModelService.from_artifacts()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail="World model artifacts are not available",
        ) from exc
    request.app.state.world_model_service = service
    return service


WorldModelServiceDep = Annotated[WorldModelService, Depends(get_world_model_service)]
RequestIdHeader = Annotated[str | None, Header(alias="X-Request-ID")]


@router.post("/hospital-world", response_model=SimulationResponse)
async def simulate_hospital_world(
    payload: SimulationRequest,
    service: WorldModelServiceDep,
    x_request_id: RequestIdHeader = None,
) -> SimulationResponse:
    """Simulate hospital workload under a sequence of planned interventions."""
    request_id = x_request_id or str(uuid4())
    LOGGER.info(
        "world_model_simulation_requested",
        hospital_id=payload.hospital_id,
        service_id=payload.service_id,
        history_length=len(payload.history_siips),
        action_length=len(payload.actions),
        request_id=request_id,
    )
    action_sequence = [action.to_vector() for action in payload.actions]
    try:
        simulate_call = partial(service.simulate, payload.history_siips, action_sequence)
        raw_results = await anyio.to_thread.run_sync(simulate_call)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        LOGGER.warning(
            "world_model_artifact_missing",
            request_id=request_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=503,
            detail="World model artifacts are not available",
        ) from exc
    except Exception as exc:
        LOGGER.exception(
            "world_model_simulation_failed",
            request_id=request_id,
            hospital_id=payload.hospital_id,
            service_id=payload.service_id,
        )
        raise HTTPException(status_code=500, detail="World model simulation failed") from exc

    return SimulationResponse(
        status="ok",
        hospital_id=payload.hospital_id,
        service_id=payload.service_id,
        model_version=service.model_version,
        results=[SimulationStepResult(**item) for item in raw_results],
    )
