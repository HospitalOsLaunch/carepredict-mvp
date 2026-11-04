"""OpenTelemetry traces of the API (règle 18 de l'audit de performance), off by default.

A trace shows where the time of a slow call goes: each SQL query, and the computations
named with :func:`span` (forecast of the exits, ranking of the requests…). Nothing is sent
unless the group names its own collector:

- ``OTEL_EXPORTER_OTLP_ENDPOINT`` (or ``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT``): OTLP over
  HTTP to the group's collector (Jaeger, Tempo, an OpenTelemetry Collector…);
- ``ADM_TRACES=console``: each span printed on the API's output, for a local diagnosis.

The standard variables of the SDK apply: ``OTEL_SERVICE_NAME`` (default
``hospitalos-api``), ``OTEL_TRACES_SAMPLER`` and ``OTEL_TRACES_SAMPLER_ARG`` (to keep one
call in ten, say), ``OTEL_EXPORTER_OTLP_HEADERS``.

Health data: a span leaves the API with an allowlist of attributes only (method, route
template, status, parameterised SQL, durations, ``hospitalos.*`` counts). The query
string (a search may hold a patient's name), the address and browser of the caller, the
SQL values and the exception messages never leave: they are dropped before export,
whatever an instrumentation library records.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.util.types import AttributeValue

if TYPE_CHECKING:
    from fastapi import FastAPI
    from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
    from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
    from sqlalchemy import Engine

SAFE_ATTRIBUTES = frozenset(
    {
        # HTTP (semantic conventions, old and new names)
        "http.method",
        "http.request.method",
        "http.route",
        "http.status_code",
        "http.response.status_code",
        "http.scheme",
        "url.scheme",
        "http.flavor",
        "network.protocol.version",
        "error.type",
        # SQL: the statement with its placeholders; the values are not recorded
        "db.system",
        "db.system.name",
        "db.name",
        "db.namespace",
        "db.operation",
        "db.operation.name",
        "db.statement",
        "db.query.text",
        # exceptions: the type only (a message may quote a value)
        "exception.type",
        "exception.escaped",
    }
)
OWN_PREFIX = "hospitalos."

_provider: TracerProvider | None = None


def safe_attributes(attributes: Mapping[str, AttributeValue] | None) -> dict[str, AttributeValue]:
    return {
        key: value
        for key, value in (attributes or {}).items()
        if key in SAFE_ATTRIBUTES or key.startswith(OWN_PREFIX)
    }


def scrub(span: ReadableSpan) -> ReadableSpan:
    """A copy of the span with the allowlisted attributes only, and no status message."""
    from opentelemetry.sdk.trace import Event, ReadableSpan
    from opentelemetry.trace import Status

    return ReadableSpan(
        name=span.name,
        context=span.context,
        parent=span.parent,
        resource=span.resource,
        attributes=safe_attributes(span.attributes),
        events=[Event(e.name, safe_attributes(e.attributes), e.timestamp) for e in span.events],
        links=span.links,
        kind=span.kind,
        status=Status(span.status.status_code),
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


def _safe_exporter(inner: SpanExporter) -> SpanExporter:
    from opentelemetry.sdk.trace.export import SpanExporter

    class SafeExporter(SpanExporter):
        """Exports through ``inner`` what :func:`scrub` keeps of each span."""

        def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
            return inner.export([scrub(s) for s in spans])

        def shutdown(self) -> None:
            inner.shutdown()

        def force_flush(self, timeout_millis: int = 30_000) -> bool:
            return inner.force_flush(timeout_millis)

    return SafeExporter()


def _configured_exporter() -> tuple[SpanExporter, bool] | None:
    """The exporter named by the environment, and whether to batch; None when tracing is off."""
    if os.environ.get("ADM_TRACES", "").strip().lower() == "console":
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        return ConsoleSpanExporter(), False
    if os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.environ.get(
        "OTEL_EXPORTER_OTLP_ENDPOINT"
    ):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        return OTLPSpanExporter(), True
    return None


def setup_tracing(
    app: FastAPI, engine: Engine, exporter: SpanExporter | None = None, batch: bool = False
) -> TracerProvider | None:
    """Traces the HTTP calls and the SQL queries of ``app`` when an exporter is configured
    (the environment, or ``exporter`` in tests). Returns the provider, or None when off."""
    global _provider
    if exporter is None:
        configured = _configured_exporter()
        if configured is None:
            return None
        exporter, batch = configured

    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor

    service = os.environ.get("OTEL_SERVICE_NAME") or "hospitalos-api"
    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    safe = _safe_exporter(exporter)
    provider.add_span_processor(BatchSpanProcessor(safe) if batch else SimpleSpanProcessor(safe))

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls="api/health",
        # One span per call, not three: the ASGI « receive » and « send » add nothing here.
        exclude_spans=["receive", "send"],
    )
    # The instrumentation declares « sqlalchemy < 2.1 » while it only uses the stable event
    # API: the dependency check would silently trace no query (a test guards it).
    SQLAlchemyInstrumentor().instrument(
        engine=engine, tracer_provider=provider, skip_dep_check=True
    )
    _provider = provider
    return provider


@contextmanager
def span(name: str, **attributes: AttributeValue) -> Iterator[trace.Span]:
    """A named step of a computation, inside the current call's trace (a no-op when off).
    Attributes are counts and sizes, under ``hospitalos.``: never a patient's data."""
    tracer = (_provider or trace.get_tracer_provider()).get_tracer("hospitalos")
    with tracer.start_as_current_span(
        name, attributes={f"{OWN_PREFIX}{k}": v for k, v in attributes.items()}
    ) as current:
        yield current
