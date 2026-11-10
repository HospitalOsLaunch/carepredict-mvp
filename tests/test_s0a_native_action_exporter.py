"""No-simulation/no-ML tests for native four-lever S0a action export."""
from __future__ import annotations

from copy import deepcopy

import pytest

from research_lab.s0a_native_action_exporter import (
    LEVIERS,
    NATIVE_SCHEMA,
    build_native_intervals,
)


def fixture() -> list[dict]:
    return [
        {
            "event_id": f"H:E{index}",
            "hospital_id": "H",
            "unit_id": unit,
            "h": 9,
            "type": "DECISION",
            "payload": dict(zip(LEVIERS, values, strict=True)),
        }
        for index, (unit, values) in enumerate((
            ("u1", (1, 0, 0, 1)), ("u2", (0, 0, 1, 0))
        ))
    ]


def build(events: list[dict] | None = None) -> list[dict]:
    return build_native_intervals(
        fixture() if events is None else events,
        hospital_id="H", units=("u1", "u2"), days=1, warmup_hours=24,
    )


def test_full_unit_hour_grid_and_native_action_semantics() -> None:
    result = build()
    assert len(result) == 48
    assert all(row["schema"] == NATIVE_SCHEMA for row in result)
    assert all(tuple(row["values"]) == LEVIERS for row in result)
    for unit, expected in (("u1", (1, 0, 0, 1)), ("u2", (0, 0, 1, 0))):
        row = next(r for r in result if r["unit_id"] == unit and r["hour"] == 9)
        assert tuple(row["values"].values()) == expected
        assert row["interval_start_h"] == 9
        assert row["interval_end_h"] == 10
        assert row["available_h"] == 10
        assert row["is_policy_decision_hour"] is True
        zeros = [r for r in result if r["unit_id"] == unit and r["hour"] != 9]
        assert all(not any(r["values"].values()) for r in zeros)
        assert all(not r["is_policy_decision_hour"] for r in zeros)


def test_missing_decision_is_not_silently_zero() -> None:
    with pytest.raises(ValueError, match="cover every"):
        build(fixture()[:1])


def test_duplicate_decision_is_rejected() -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        build(fixture() + [fixture()[0]])


def test_four_native_levers_must_be_exact() -> None:
    events = fixture()
    events[0]["payload"] = {"staffing_delta": 0.2, "discharge_delta": 0.1}
    with pytest.raises(ValueError, match="four original levers"):
        build(events)


def test_future_or_nonbinary_decisions_fail() -> None:
    events = fixture()
    events[0]["payload"]["renfort_soignant"] = 0.5
    with pytest.raises(ValueError, match="binary"):
        build(events)
    events = fixture()
    events[0]["h"] = 10
    with pytest.raises(ValueError, match="09:00"):
        build(events)


def test_unknown_hospital_and_units_fail() -> None:
    events = fixture()
    events[0]["unit_id"] = "unknown"
    with pytest.raises(ValueError, match="Unknown source"):
        build(events)
    with pytest.raises(ValueError, match="Invalid hospital"):
        build_native_intervals(fixture(), hospital_id="H",
                               units=("u1", "u1"), days=1, warmup_hours=24)


def test_warmup_and_out_of_period_events_not_exported() -> None:
    events = fixture()
    extra = deepcopy(events[0])
    extra["h"] = -15
    extra["event_id"] = "H:warmup"
    assert build(events + [extra]) == build()


def test_only_decision_events_accepted_as_actions() -> None:
    events = fixture()
    events.append({
        "type": "RECOMMANDATION", "hospital_id": "H",
        "unit_id": "u1", "h": 9,
        "payload": dict.fromkeys(LEVIERS, 1),
    })
    assert build(events) == build()
