"""Regression cases from the independent review; no schema-v1 extension."""

from __future__ import annotations

from typing import Any

import pytest

from services.validation.validator import Decision, validate_batch


def row(**updates: Any) -> dict[str, Any]:
    return {
        "hospital_id": "H_DEMO",
        "service_id": "U_DEMO",
        "source_system": "synthetic",
        "event_time": "2026-08-11T08:00:00+02:00",
        "available_at": "2026-08-11T08:05:00+02:00",
        "action_type": "staffing_change",
        "magnitude": 1.0,
        "target_service_id": "U_DEMO",
        **updates,
    }


@pytest.mark.parametrize("changed", [False, True])
def test_same_instant_with_different_serialization(changed: bool) -> None:
    a = row()
    b = row(
        event_time="2026-08-11T08:00:00.000000+02:00",
        available_at="2026-08-11T08:05:00.000000+02:00",
        magnitude=2.0 if changed else 1.0,
    )
    report = validate_batch([a, b], "actions", run_id="identity")
    assert report.decision is Decision.NO_GO
    assert {f.code for f in report.findings} == {
        "conflicting_restatement" if changed else "duplicate_record"
    }


@pytest.mark.parametrize(
    "updates",
    [
        {"action_type": "bed_management"},
        {"target_service_id": "U_OTHER"},
        {"available_at": "2026-08-11T08:06:00+02:00"},
    ],
)
def test_distinct_actions_and_restatements_are_valid(updates: dict[str, Any]) -> None:
    assert (
        validate_batch([row(), row(**updates)], "actions", run_id="identity").decision
        is Decision.GO
    )


def test_implicit_target_is_same_effective_target() -> None:
    report = validate_batch([row(), row(target_service_id=None)], "actions", run_id="identity")
    assert any(f.code == "duplicate_record" for f in report.findings)


def test_snapshots_still_reject_semantic_duplicate() -> None:
    a = {
        k: v for k, v in row().items() if k not in {"action_type", "magnitude", "target_service_id"}
    }
    a.update(siips_score=42.0, aas_score=10.0, patient_count=24)
    b = {**a, "event_time": "2026-08-11T08:00:00.000000+02:00"}
    report = validate_batch([a, b], "care_load", run_id="identity")
    assert report.decision is Decision.NO_GO
    assert {f.code for f in report.findings} == {"duplicate_record"}


def test_fall_back_hours_are_distinct_instants() -> None:
    a = row(event_time="2026-10-25T02:00:00+02:00", available_at="2026-10-25T02:05:00+02:00")
    b = row(event_time="2026-10-25T02:00:00+01:00", available_at="2026-10-25T02:05:00+01:00")
    assert validate_batch([a, b], "actions", run_id="identity").decision is Decision.GO
