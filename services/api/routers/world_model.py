"""Synthetic decision and retrospective review. Only local demo apps opt in."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response

from hospitalos.world_model import engine
from hospitalos.world_model.contracts import Advance, Confirm, Contexts, Session, Start
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
                model_version=engine.manifest()["version"],
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
        return respond(response, lambda: store.mutate(str(identifier), "confirm", body.option_id))

    @router.post("/sessions/{identifier}/advance")
    def advance(identifier: UUID, body: Advance, response: Response) -> Session:
        return respond(response, lambda: store.mutate(str(identifier), "advance", body.from_hour))

    return router
