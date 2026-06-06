"""CarePredict prediction API."""

from __future__ import annotations

import structlog
from fastapi import FastAPI

from services.api.middleware.prometheus import PrometheusMiddleware, metrics_response
from services.api.routers import health, predict

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)

app = FastAPI(
    title="CarePredict API",
    version="0.1.0",
    description="J+12h nursing workload prediction API.",
)
app.add_middleware(PrometheusMiddleware)
app.include_router(health.router)
app.include_router(predict.router)


@app.get("/metrics", include_in_schema=False)
def metrics() -> object:
    """Prometheus metrics endpoint."""
    return metrics_response()
