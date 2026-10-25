"""FastAPI application factory. Run with:

uvicorn services.admissions_smr.main:app --port 8010
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.admissions_smr import __version__
from services.admissions_smr.api import (
    routes_auth,
    routes_imports,
    routes_insights,
    routes_requests,
    routes_sites,
    routes_stays,
)
from services.admissions_smr.clock import Clock
from services.admissions_smr.config import Settings, get_settings
from services.admissions_smr.db import Base, make_engine, make_session_factory


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)

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
        routes_auth,
        routes_sites,
        routes_requests,
        routes_stays,
        routes_insights,
        routes_imports,
    ):
        api.include_router(module.router)
    app.include_router(api)
    return app


def __getattr__(name: str) -> FastAPI:
    # Lazy module-level ``app`` so importing this module in tests does not touch a database.
    if name == "app":
        return create_app()
    raise AttributeError(name)
