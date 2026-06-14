"""CarePredict prediction API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from services.api.dependencies.feature_fetcher import FeastFeatureFetcher
from services.api.dependencies.model_loader import load_prediction_model_bundle
from services.api.middleware.prometheus import PrometheusMiddleware, metrics_response
from services.api.routers import forecast, health, predict, simulate
from services.api.runtime import configure_torch_runtime

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize process-wide serving state once per API worker."""
    configure_torch_runtime()
    app.state.feature_fetcher = FeastFeatureFetcher()
    app.state.model_bundle = load_prediction_model_bundle()
    yield


app = FastAPI(
    title="CarePredict API",
    version="0.1.0",
    description="J+12h nursing workload prediction API.",
    lifespan=lifespan,
)
app.add_middleware(PrometheusMiddleware)
app.include_router(health.router)
app.include_router(predict.router)
app.include_router(simulate.router)
app.include_router(forecast.router)


@app.get("/metrics", include_in_schema=False)
def metrics() -> object:
    """Prometheus metrics endpoint."""
    return metrics_response()
