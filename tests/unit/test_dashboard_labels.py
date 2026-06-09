"""Tests for dashboard French label helpers."""

from __future__ import annotations

from dashboards.labels import (
    ACTION_COLUMN_LABELS,
    fr_action_columns,
    fr_service_name,
    status_from_score,
)


def test_fr_action_columns_translates_known() -> None:
    """Known action columns are translated to French display labels."""
    columns = list(ACTION_COLUMN_LABELS)
    assert fr_action_columns(columns) == list(ACTION_COLUMN_LABELS.values())


def test_fr_action_columns_passthrough_unknown() -> None:
    """Unknown action columns are preserved unchanged."""
    assert fr_action_columns(["unknown_column"]) == ["unknown_column"]


def test_fr_service_name_known() -> None:
    """Known service identifiers are translated."""
    assert fr_service_name("urg-001") == "Urgences"


def test_fr_service_name_passthrough() -> None:
    """Unknown service identifiers pass through unchanged."""
    assert fr_service_name("unknown-001") == "unknown-001"


def test_status_from_score_critical() -> None:
    """Scores at or above threshold are critical."""
    assert status_from_score(900.0, 850.0) == "critical"


def test_status_from_score_watch() -> None:
    """Scores in the watch band are marked watch."""
    assert status_from_score(750.0, 850.0) == "watch"


def test_status_from_score_normal() -> None:
    """Scores below the watch band are normal."""
    assert status_from_score(500.0, 850.0) == "normal"
