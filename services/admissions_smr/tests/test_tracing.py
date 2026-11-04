"""Traces of the API (règle 18): off by default, and nothing identifying ever leaves."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from services.admissions_smr import tracing
from services.admissions_smr.models import Group

TRACING_VARIABLES = (
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "ADM_TRACES",
)


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemorySpanExporter]:
    """Tracing on for the app the test builds, into memory (as if a collector were named)."""
    memory = InMemorySpanExporter()
    monkeypatch.setattr(tracing, "_configured_exporter", lambda: (memory, False))
    yield memory
    SQLAlchemyInstrumentor().uninstrument()
    monkeypatch.setattr(tracing, "_provider", None)


def dump(spans: tuple[ReadableSpan, ...]) -> str:
    return repr(
        [
            (
                s.name,
                dict(s.attributes or {}),
                [(e.name, dict(e.attributes or {})) for e in s.events],
            )
            for s in spans
        ]
    )


def test_tracing_is_off_unless_the_group_names_a_collector(
    monkeypatch: pytest.MonkeyPatch, app_client: TestClient
) -> None:
    for name in TRACING_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    assert tracing._configured_exporter() is None
    middleware = [m.cls.__name__ for m in app_client.app.user_middleware]  # type: ignore[attr-defined]
    assert not any("OpenTelemetry" in name for name in middleware)

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collecteur.ght.local:4318")
    configured = tracing._configured_exporter()
    assert configured is not None
    exporter, batched = configured
    assert type(exporter).__name__ == "OTLPSpanExporter" and batched


def test_a_trace_shows_the_queries_and_the_steps_but_no_patient_data(
    spans: InMemorySpanExporter,
    app_client: TestClient,
    make_group: Callable[[str], Group],
    login: Callable[[str], dict[str, str]],
) -> None:
    make_group("g1")
    headers = {**login("coord@g1.fr"), "User-Agent": "Navigateur-Du-Cadre/1.0"}
    spans.clear()

    # A search by a patient's name: the query string must not leave the API.
    response = app_client.get(
        "/api/requests", params={"scope": "toutes", "q": "Martin Dupont"}, headers=headers
    )
    assert response.status_code == 200
    out = spans.get_finished_spans()

    root = next(s for s in out if s.parent is None)
    assert root.attributes is not None
    assert root.attributes["http.route"] == "/api/requests"
    assert root.attributes["http.status_code"] == 200
    # SQL is traced (the instrumentation's own version check would silently skip it).
    statements = [str((s.attributes or {}).get("db.statement", "")) for s in out]
    assert any("FROM admission_requests" in st for st in statements)
    context = next(s for s in out if s.name == "requests.context")
    sites = (context.attributes or {})["hospitalos.sites"]
    assert isinstance(sites, int) and sites >= 1
    assert any(s.name == "forecast.fit_hazard" for s in out)

    text = dump(out)
    for leaked in ("Martin", "Dupont", "q=", "Navigateur-Du-Cadre", "testclient"):
        assert leaked not in text, leaked


def test_an_exception_leaves_its_type_but_not_its_message() -> None:
    memory = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(tracing._safe_exporter(memory)))
    with pytest.raises(ValueError), provider.get_tracer("t").start_as_current_span("step"):
        raise ValueError("Dupont Martine, née le 02/03/1941")

    (exported,) = memory.get_finished_spans()
    assert [e.name for e in exported.events] == ["exception"]
    assert (exported.events[0].attributes or {})["exception.type"] == "ValueError"
    assert exported.status.description is None
    assert "Dupont" not in dump((exported,)) and "1941" not in dump((exported,))


def test_own_steps_keep_their_counts() -> None:
    assert tracing.safe_attributes(
        {
            "hospitalos.stays": 120,
            "http.target": "/api/requests?q=Martin",
            "client.address": "10.1.2.3",
        }
    ) == {"hospitalos.stays": 120}
