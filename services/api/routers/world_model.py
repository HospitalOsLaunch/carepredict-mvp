"""Synthetic decision and retrospective review. Only local demo apps opt in."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response

from hospitalos.world_model import engine
from hospitalos.world_model.contracts import (
    Advance,
    Confirm,
    Contexts,
    Objective,
    PlanConfirmation,
    PlanEvaluation,
    PlanMenu,
    PlanPreview,
    PlanRequest,
    Session,
    Start,
    WardState,
)
from hospitalos.world_model.physics import ModelUnavailable
from hospitalos.world_model.sessions import Conflict, SessionStore, Unknown

T = TypeVar("T")


def respond(response: Response, operation: Callable[[], T]) -> T:
    response.headers["Cache-Control"] = "no-store"
    try:
        return operation()
    except Unknown as exc:
        raise HTTPException(404, str(exc)) from exc
    except Conflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ModelUnavailable as exc:
        raise HTTPException(
            503,
            "Moteur indisponible. Vérifiez les fichiers du modèle et le compilateur C++17.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def world_model_router(store: SessionStore) -> APIRouter:
    router = APIRouter(prefix="/world-model", tags=["Synthetic world model"])

    @router.get("/contexts")
    def contexts(response: Response) -> Contexts:
        return respond(
            response,
            lambda: Contexts(
                contexts=[case.context for case in engine.cases().values()],
                model_version=engine.model_version(),
            ),
        )

    @router.put("/sessions/{identifier}")
    def start(identifier: UUID, body: Start, response: Response) -> Session:
        return respond(response, lambda: store.start(str(identifier), body.context_id))

    @router.get("/sessions/{identifier}")
    def get(identifier: UUID, response: Response) -> Session:
        return respond(response, lambda: store.get(str(identifier)))

    @router.post("/sessions/{identifier}/confirm")
    def confirm(identifier: UUID, body: Confirm, response: Response) -> Session:
        return respond(
            response,
            lambda: store.mutate(
                str(identifier), "confirm", body.option_id, objective=body.objective
            ),
        )

    @router.post("/sessions/{identifier}/advance")
    def advance(identifier: UUID, body: Advance, response: Response) -> Session:
        return respond(response, lambda: store.mutate(str(identifier), "advance", body.from_hour))

    @router.get("/sessions/{identifier}/wards/{ward_id}/state")
    def unit_state(identifier: UUID, ward_id: str, response: Response) -> WardState:
        return respond(response, lambda: store.unit_state(str(identifier), ward_id))

    @router.get("/sessions/{identifier}/plans")
    def plans(
        identifier: UUID,
        response: Response,
        objective: Objective = "transfer_queue",
        ward_id: str | None = None,
    ) -> PlanMenu:
        return respond(response, lambda: store.plan_menu(str(identifier), objective, ward_id))

    @router.post("/sessions/{identifier}/plans/preview")
    def preview(identifier: UUID, body: PlanPreview, response: Response) -> PlanEvaluation:
        return respond(response, lambda: store.plan_preview(str(identifier), body))

    @router.post("/sessions/{identifier}/plans/optimize")
    def optimize(identifier: UUID, body: PlanRequest, response: Response) -> PlanMenu:
        return respond(response, lambda: store.plan_optimize(str(identifier), body))

    @router.post("/sessions/{identifier}/plans/confirm")
    def confirm_plan(identifier: UUID, body: PlanConfirmation, response: Response) -> Session:
        return respond(response, lambda: store.confirm_plan(str(identifier), body))

    return router
