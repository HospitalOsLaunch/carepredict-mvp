"""Prometheus latency middleware."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from prometheus_client import Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware

REQUEST_COUNT = Counter(
    "carepredict_api_requests_total",
    "Total API requests",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "carepredict_api_request_latency_seconds",
    "API request latency",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Record request counters and latency histograms."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        path = request.url.path
        REQUEST_COUNT.labels(request.method, path, str(response.status_code)).inc()
        REQUEST_LATENCY.labels(request.method, path).observe(elapsed)
        return response


def metrics_response() -> Response:
    """Return Prometheus text exposition."""
    return Response(generate_latest(), media_type="text/plain; version=0.0.4")
