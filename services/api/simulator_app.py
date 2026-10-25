"""Explicit local simulation gateway. Existing hybrid app remains observation-only."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from threading import Lock
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from hospitalos.hybrid.live_models import LiveSnapshot, PlanningOptions, ShadowEpisode
from hospitalos.simulator.comparison import (
    ComparisonEnvironmentChanged,
    ComparisonRequest,
    ComparisonResult,
    compare,
)
from hospitalos.simulator.session import ControlRequest, DecisionRequest, DemoSession, DemoView
from services.api.hybrid_app import create_app as create_hybrid_app


def create_app(session: DemoSession) -> FastAPI:
    app = create_hybrid_app()
    comparison_lock = Lock()
    app.title = "HospitalOS - démonstration dynamique locale"
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"]
    )

    @app.middleware("http")
    async def local_origin(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).hostname not in {"localhost", "127.0.0.1", "::1"}:
            return JSONResponse({"detail": "local_demo_origin_required"}, status_code=403)
        return await call_next(request)

    @app.get("/demo/session", response_model=DemoView)
    def status() -> DemoView:
        return session.view()

    @app.post("/demo/compare", response_model=ComparisonResult)
    def compare_episodes(request: ComparisonRequest) -> ComparisonResult:
        # Bound CPU work to one pair at a time; interactive state is never locked or changed.
        if not comparison_lock.acquire(blocking=False):
            raise HTTPException(status_code=429, detail="comparison_already_running")
        try:
            return compare(request)
        except ComparisonEnvironmentChanged as error:
            raise HTTPException(
                status_code=503, detail="comparison_environment_changed_restart_required"
            ) from error
        finally:
            comparison_lock.release()

    @app.post("/demo/evaluate", response_model=DemoView)
    def assess() -> DemoView:
        try:
            session.assess()
            return session.view()
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/demo/control", response_model=DemoView)
    def control(request: ControlRequest) -> DemoView:
        try:
            return session.control(request)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/demo/decision", response_model=DemoView)
    def decide(request: DecisionRequest) -> DemoView:
        try:
            return session.decide(request)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/hybrid/live", response_model=LiveSnapshot)
    def live() -> LiveSnapshot:
        return session.view().snapshot

    @app.post("/hybrid/shadow", response_model=ShadowEpisode)
    def shadow(options: PlanningOptions) -> ShadowEpisode:
        try:
            return session.assess(options)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    return app
