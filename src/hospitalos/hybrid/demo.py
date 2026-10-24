"""Small fictional fixture, deliberately insufficient for a performance claim."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .models import Bed, FactEvent, Patient, Unit
from .planning import PlanRequest


def demo_request() -> PlanRequest:
    at = datetime(2026, 10, 24, 8, tzinfo=UTC)
    facts = (
        Unit(id="medicine", staffed_beds=2, cleaning_teams=1),
        Bed(id="bed-a", unit_id="medicine", state="dirty"),
        Bed(id="bed-z", unit_id="medicine", state="dirty", capabilities=("oxygen",)),
        Patient(
            id="fictional-p1",
            status="waiting",
            compatible_units=("medicine",),
            requirements=("oxygen",),
            waiting_since=at - timedelta(hours=1),
        ),
    )
    return PlanRequest(
        hospital_id="fictional-hospital",
        at=at,
        expected_entities=tuple(f"{f.kind}:{f.id}" for f in facts),
        events=tuple(
            FactEvent(
                hospital_id="fictional-hospital",
                event_id=f"demo:{f.kind}:{f.id}",
                source="fictional_feed",
                event_time=at,
                available_at=at,
                fact=f,
            )
            for f in facts
        ),
    )
