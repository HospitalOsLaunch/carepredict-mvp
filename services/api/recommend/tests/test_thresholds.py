"""Unit tests for service-specific threshold providers."""

from __future__ import annotations

from services.api.recommend.thresholds import DEFAULT_RISK_THRESHOLD, TimescaleP90ThresholdProvider


class FakeCursor:
    """Tiny DB cursor fixture."""

    def __init__(self, rows: list[tuple[float | None]]) -> None:
        self.rows = rows
        self.queries = 0

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, params: tuple[str, str]) -> None:
        self.queries += 1
        self.last_query = query
        self.last_params = params

    def fetchone(self) -> tuple[float | None]:
        return self.rows[0]


class FakeConnection:
    """Tiny DB connection fixture."""

    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return self._cursor


def _provider(cursor: FakeCursor) -> TimescaleP90ThresholdProvider:
    return TimescaleP90ThresholdProvider(
        dsn="postgresql://unit-test",
        connect_factory=lambda dsn: FakeConnection(cursor),
    )


def test_threshold_for_returns_percentile_value() -> None:
    cursor = FakeCursor(rows=[(742.5,)])

    threshold = _provider(cursor).threshold_for(hospital_id="hosp-001", service_id="urg-001")

    assert threshold == 742.5
    assert "percentile_cont(0.9)" in cursor.last_query
    assert cursor.last_params == ("hosp-001", "urg-001")


def test_threshold_for_null_uses_fallback() -> None:
    cursor = FakeCursor(rows=[(None,)])

    threshold = _provider(cursor).threshold_for(hospital_id="hosp-001", service_id="unknown-001")

    assert threshold == DEFAULT_RISK_THRESHOLD


def test_threshold_for_uses_instance_cache() -> None:
    cursor = FakeCursor(rows=[(912.0,)])
    provider = _provider(cursor)

    first = provider.threshold_for(hospital_id="hosp-001", service_id="rea-001")
    second = provider.threshold_for(hospital_id="hosp-001", service_id="rea-001")

    assert first == second == 912.0
    assert cursor.queries == 1
