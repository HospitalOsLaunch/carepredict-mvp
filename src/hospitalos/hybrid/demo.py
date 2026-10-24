"""Small fictional fixture, deliberately insufficient for a performance claim."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .models import Bed, Discharge, FactEvent, Patient, ResourcePool, Unit
from .planning import PlanRequest
from .simulation import Assumptions


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


def pathway_request() -> PlanRequest:
    """One blocked departure unlocks one compatible bed in a fictional unit."""
    at = datetime(2026, 10, 24, 8, tzinfo=UTC)
    facts = (
        Unit(id="medicine", staffed_beds=1, cleaning_teams=1),
        Bed(
            id="bed-1",
            unit_id="medicine",
            state="occupied",
            occupant="outgoing",
            capabilities=("oxygen",),
        ),
        Patient(
            id="outgoing",
            status="admitted",
            bed_id="bed-1",
            compatible_units=("medicine",),
            waiting_since=at - timedelta(days=1),
            medically_cleared=True,
            downstream_confirmed=True,
        ),
        Patient(
            id="incoming",
            status="waiting",
            compatible_units=("medicine",),
            requirements=("oxygen",),
            waiting_since=at - timedelta(hours=1),
        ),
        Discharge(
            id="outgoing",
            documents_ready=True,
            escort_required=False,
            downstream_required=True,
            downstream_pool_id="smr",
            transport_required=True,
            transport_pool_id="transport",
            transport_requested=False,
        ),
        ResourcePool(id="smr", resource="downstream", unit_ids=("medicine",), available=1),
        ResourcePool(id="transport", resource="transport", unit_ids=("medicine",), available=1),
    )
    return PlanRequest(
        hospital_id="fictional-hospital",
        at=at,
        expected_entities=tuple(f"{f.kind}:{f.id}" for f in facts),
        events=tuple(
            FactEvent(
                hospital_id="fictional-hospital",
                event_id=f"pathway:{f.kind}:{f.id}",
                source="fictional_feed",
                event_time=at,
                available_at=at,
                fact=f,
            )
            for f in facts
        ),
        assumptions=Assumptions(
            departure_minutes=(30,),
            transport_minutes=(45,),
            transport_return_minutes=(30,),
            cleaning_minutes=(30,),
            load_multipliers=(1,),
        ),
        horizon_minutes=360,
    )
