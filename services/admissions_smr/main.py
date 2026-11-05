"""FastAPI application factory. Run with:

uvicorn services.admissions_smr.main:app --port 8010
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from services.admissions_smr import __version__
from services.admissions_smr.agent_replay import purge_steps
from services.admissions_smr.api import (
    routes_agent,
    routes_auth,
    routes_beds,
    routes_connections,
    routes_ed,
    routes_forecast_store,
    routes_hl7,
    routes_imports,
    routes_insights,
    routes_predictions,
    routes_replay,
    routes_requests,
    routes_ror,
    routes_sites,
    routes_stays,
    routes_web_vitals,
)
from services.admissions_smr.clock import Clock
from services.admissions_smr.config import Settings, get_settings
from services.admissions_smr.db import make_engine, make_session_factory
from services.admissions_smr.migrate import upgrade
from services.admissions_smr.tracing import setup_tracing


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    upgrade(engine)

    app = FastAPI(
        title="HospitalOS — Admissions SMR",
        version=__version__,
        description=(
            "Pilote d'admissions pour groupes SMR : demandes priorisées, prévision des sorties, "
            "réponse en un clic à l'adresseur, indicateurs pilote."
        ),
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.clock = clock or Clock(settings.timezone)
    app.state.replay_purged_at = {}  # group id -> last heartbeat purge of the agent player
    with app.state.session_factory() as session:
        purge_steps(session, app.state.clock.now(), settings.agent_replay_days)
        session.commit()

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        """422 without ``input`` / ``ctx``: a rejected value (a name typed in the wrong
        field, a value read on a screen) is never echoed back or logged (REVIEW S-M2)."""
        detail = [
            {key: error[key] for key in ("loc", "msg", "type") if key in error}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": jsonable_encoder(detail)})

    app.add_middleware(routes_replay.StepUploadLimit)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )

    api = APIRouter(prefix="/api")

    @api.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    for module in (
        routes_agent,
        routes_connections,
        routes_replay,
        routes_auth,
        routes_sites,
        routes_requests,
        routes_stays,
        routes_insights,
        routes_predictions,
        routes_ror,
        routes_imports,
        routes_beds,
        routes_ed,
        routes_hl7,
        routes_forecast_store,
        routes_web_vitals,
    ):
        api.include_router(module.router)
    app.include_router(api)
    # Off unless the group names its collector (OTEL_EXPORTER_OTLP_ENDPOINT): règle 18.
    setup_tracing(app, engine)
    return app


def __getattr__(name: str) -> FastAPI:
    # Lazy module-level ``app`` so importing this module in tests does not touch a database.
    if name == "app":
        return create_app()
    raise AttributeError(name)
