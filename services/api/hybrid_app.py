"""Local prototype API; no authentication, hospital connector or execution endpoint.

Loopback only. Optional live routes require an immutable shadow-mode store.
Receipt ingestion remains a trusted local adapter operation, never a public API.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException

from hospitalos.hybrid.live_models import LiveSnapshot, PlanningOptions, ShadowEpisode
from hospitalos.hybrid.live_store import LiveStore
from hospitalos.hybrid.planning import Plan, PlanRequest, plan


def create_app(
    live: LiveStore | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> FastAPI:
    if live is not None and live.policy.mode != "shadow":
        raise ValueError("The local API only accepts a shadow-mode store")
    app = FastAPI(title="HospitalOS Hybrid MVP - local prototype", version="0.2.0")

    @app.post("/hybrid/plan", response_model=Plan)
    def recommend(request: PlanRequest) -> Plan:
        try:
            return plan(request)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "local_prototype_no_external_execution"}

    if live is not None:

        @app.get("/hybrid/live", response_model=LiveSnapshot)
        def snapshot() -> LiveSnapshot:
            assert live is not None
            try:
                return live.snapshot(clock())
            except ValueError as error:
                raise HTTPException(status_code=409, detail=str(error)) from error

        @app.post("/hybrid/shadow", response_model=ShadowEpisode)
        def record(options: PlanningOptions) -> ShadowEpisode:
            assert live is not None
            try:
                return live.record_shadow(clock(), options)
            except ValueError as error:
                raise HTTPException(status_code=409, detail=str(error)) from error

    return app


app = create_app()
