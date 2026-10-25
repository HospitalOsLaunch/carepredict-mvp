"""Normal product API, scoped to named fictional hospitals; no scenario control routes."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from hospitalos.virtual.campus import CampusFleet
from hospitalos.virtual.operations import Operation
from hospitalos.virtual.runtime import Decision, HospitalRuntime, HospitalView, VirtualFleet


def create_app(fleet: VirtualFleet | CampusFleet, *, start_worker: bool = True) -> FastAPI:
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

    @app.get("/product/hospitals/H1/workspace")
    def workspace() -> dict[str, Any]:
        if not isinstance(fleet, CampusFleet) or fleet.ops is None:
            raise HTTPException(status_code=404, detail="unknown_workspace")
        with fleet.lock:
            if fleet.errors:
                raise HTTPException(status_code=503, detail="hospital_feed_unavailable")
            return fleet.ops.view()

    @app.post("/product/hospitals/H1/operations")
    def operate(operation: Operation) -> dict[str, Any]:
        if not isinstance(fleet, CampusFleet) or fleet.ops is None:
            raise HTTPException(status_code=404, detail="unknown_workspace")
        try:
            if fleet.errors:
                raise RuntimeError("hospital_feed_unavailable")
            return fleet.ops.submit(operation)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="unknown_unit_or_entity") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail="hospital_feed_unavailable") from error

    @app.get("/product/hospitals/H1/overview")
    def overview() -> dict[str, Any]:
        if not isinstance(fleet, CampusFleet):
            raise HTTPException(status_code=404, detail="unknown_hospital")
        return fleet.overview()

    @app.get("/product/hospitals/H1/units/{unit_id}/history")
    def history(unit_id: str) -> dict[str, Any]:
        if not isinstance(fleet, CampusFleet):
            raise HTTPException(status_code=404, detail="unknown_hospital")
        unit = hospital(unit_id)
        with fleet.lock, unit.lock:
            return fleet.histories[unit_id].summary()

    @app.get("/product/hospitals/H1/units/{unit_id}/history/export")
    def export_history(unit_id: str) -> Response:
        import csv
        import io

        if not isinstance(fleet, CampusFleet):
            raise HTTPException(status_code=404, detail="unknown_hospital")
        unit = hospital(unit_id)
        with fleet.lock, unit.lock:
            stream = io.StringIO()
            writer = csv.DictWriter(stream, fieldnames=["at", "occupied", "waiting", "ready"])
            writer.writeheader()
            writer.writerows(fleet.histories[unit_id].export_rows())
        return Response(
            stream.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="H1-{unit_id}-history.csv"'},
        )

    @app.get("/product/hospitals/H1/units/{unit_id}", response_model=HospitalView)
    def campus_unit(unit_id: str) -> HospitalView:
        if not isinstance(fleet, CampusFleet):
            raise HTTPException(status_code=404, detail="unknown_hospital")
        with fleet.lock:
            return hospital(unit_id).view()

    @app.post("/product/hospitals/H1/units/{unit_id}/decisions", response_model=HospitalView)
    def campus_decide(unit_id: str, decision: Decision) -> HospitalView:
        if not isinstance(fleet, CampusFleet):
            raise HTTPException(status_code=404, detail="unknown_hospital")
        if decision.unit_id != unit_id:
            raise HTTPException(status_code=409, detail="unit_mismatch")
        raise HTTPException(status_code=409, detail="named_operator_workspace_required")

    @app.get("/product/hospitals")
    def catalog() -> dict[str, object]:
        if isinstance(fleet, CampusFleet):
            return {
                "schema_version": "HOSPITAL_WORKSPACE_1",
                "synthetic": True,
                "hospitals": [
                    {
                        "id": "H1",
                        "name": "Hôpital Saint-Clair · virtuel",
                        "units": [
                            {
                                "id": key,
                                "name": unit.config.unit_name,
                                "available": key not in fleet.errors,
                            }
                            for key, unit in fleet.units.items()
                        ],
                    }
                ],
            }
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
        if isinstance(fleet, CampusFleet):
            raise HTTPException(status_code=404, detail="unit_route_required")
        return hospital(hospital_id).view()

    @app.post("/product/hospitals/{hospital_id}/decisions", response_model=HospitalView)
    def decide(hospital_id: str, decision: Decision) -> HospitalView:
        if isinstance(fleet, CampusFleet):
            raise HTTPException(status_code=404, detail="unit_route_required")
        try:
            return hospital(hospital_id).decide(decision)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    return app
