"""Normal product API, scoped to named fictional hospitals; no scenario control routes."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from hospitalos.virtual.runtime import Decision, HospitalRuntime, HospitalView, VirtualFleet


def create_app(fleet: VirtualFleet, *, start_worker: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            if start_worker:
                fleet.start()
            yield
        finally:
            fleet.close()

    app = FastAPI(title="HospitalOS — hôpitaux virtuels connectés", lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"]
    )

    @app.middleware("http")
    async def local_origin(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).hostname not in {"localhost", "127.0.0.1", "::1"}:
            return JSONResponse({"detail": "local_virtual_origin_required"}, status_code=403)
        return await call_next(request)

    def hospital(hospital_id: str) -> HospitalRuntime:
        try:
            return fleet.get(hospital_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="unknown_hospital") from error
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail="hospital_feed_unavailable") from error

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "status": "degraded" if fleet.errors else "ok",
            "mode": "virtual_hospitals",
            "schema_version": "HOSPITAL_WORKSPACE_1",
        }

    @app.get("/product/hospitals")
    def catalog() -> dict[str, object]:
        return {
            "schema_version": "HOSPITAL_WORKSPACE_1",
            "synthetic": True,
            "hospitals": [
                {
                    "id": key,
                    "name": unit.config.name,
                    "unit_name": unit.config.unit_name,
                    "available": key not in fleet.errors,
                }
                for key, unit in fleet.units.items()
            ],
        }

    @app.get("/product/hospitals/{hospital_id}/unit", response_model=HospitalView)
    def unit_view(hospital_id: str) -> HospitalView:
        return hospital(hospital_id).view()

    @app.post("/product/hospitals/{hospital_id}/decisions", response_model=HospitalView)
    def decide(hospital_id: str, decision: Decision) -> HospitalView:
        try:
            return hospital(hospital_id).decide(decision)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    return app
