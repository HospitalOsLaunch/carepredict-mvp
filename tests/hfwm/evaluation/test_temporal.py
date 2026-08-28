"""Tests for future observation, target and action leakage guards."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hfwm.evaluation.temporal import PointInTimeValue, validate_snapshot_inputs


def test_point_in_time_guard_rejects_future_observation_action_and_target() -> None:
    """Only knowledge available by origin may enter a factual feature snapshot."""
    origin = datetime(2026, 1, 1, tzinfo=UTC)
    values = (
        PointInTimeValue("safe", origin - timedelta(hours=2), origin, "observation"),
        PointInTimeValue(
            "late",
            origin - timedelta(hours=3),
            origin + timedelta(seconds=1),
            "observation",
        ),
        PointInTimeValue("future-action", origin + timedelta(hours=1), origin, "action"),
        PointInTimeValue("target", origin + timedelta(hours=6), origin, "target"),
    )
    assert validate_snapshot_inputs(values, origin_at=origin) == [
        "future_action_leakage:future-action",
        "future_observation_leakage:late",
        "target_in_features:target",
    ]


def test_point_in_time_guard_accepts_available_history() -> None:
    """Past observations available at origin are accepted."""
    origin = datetime(2026, 1, 1, tzinfo=UTC)
    values = (PointInTimeValue("safe", origin - timedelta(hours=2), origin, "context"),)
    assert validate_snapshot_inputs(values, origin_at=origin) == []
