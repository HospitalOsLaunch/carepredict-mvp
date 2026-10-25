"""Fictional medium-sized unit used only to exercise the cockpit against the real planner.

Every identifier is fictional and pseudonymous. Durations are synthetic hypotheses.
Nothing here is calibrated on, or representative of, a real hospital.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hospitalos.hybrid.live_models import Availability, LivePolicy, ObservationBatch, Resource
from hospitalos.hybrid.models import Bed, Discharge, Fact, FactEvent, Patient, ResourcePool, Unit
from hospitalos.hybrid.planning import PlanRequest
from hospitalos.hybrid.scenarios import (
    ArrivalBatch,
    BedAdmissions,
    FutureAssumptions,
    ResourceChange,
)
from hospitalos.hybrid.simulation import Assumptions

HOSPITAL = "ch-fictif"
UNIT = "medecine-polyvalente"
SOURCE = "flux-fictif"
AT = datetime(2026, 10, 24, 6, 30, tzinfo=UTC)  # 08:30 Europe/Paris

ASSUMPTIONS = Assumptions(
    cleaning_minutes=(30, 45, 60),
    departure_minutes=(30, 60, 90),
    transport_minutes=(30, 45, 75),
    transport_return_minutes=(30, 45),
    load_multipliers=(1, 1, 2),
)


def _admitted(
    pid: str, bed: str, *, hours: int, cleared: bool | None, aval: bool | None
) -> Patient:
    return Patient(
        id=pid,
        status="admitted",
        bed_id=bed,
        compatible_units=(UNIT,),
        waiting_since=AT - timedelta(hours=hours),
        medically_cleared=cleared,
        downstream_confirmed=aval,
    )


def _waiting(pid: str, *, minutes: int, priority: int, oxygen: bool = False) -> Patient:
    return Patient(
        id=pid,
        status="waiting",
        compatible_units=(UNIT,),
        requirements=("oxygene",) if oxygen else (),
        priority=priority,
        waiting_since=AT - timedelta(minutes=minutes),
    )


def facts() -> tuple[tuple[Fact, int], ...]:
    """(fact, age in minutes at AT) — ages vary so freshness is visible in the UI."""
    o2 = ("oxygene",)
    beds: list[tuple[Fact, int]] = [
        (Bed(id="L01", unit_id=UNIT, state="occupied", occupant="P-0371"), 3),
        (Bed(id="L02", unit_id=UNIT, state="occupied", occupant="P-0412", capabilities=o2), 3),
        (Bed(id="L03", unit_id=UNIT, state="occupied", occupant="P-0402"), 3),
        (Bed(id="L04", unit_id=UNIT, state="occupied", occupant="P-0420"), 3),
        (Bed(id="L05", unit_id=UNIT, state="dirty"), 12),
        (Bed(id="L06", unit_id=UNIT, state="occupied", occupant="P-0388"), 3),
        (Bed(id="L07", unit_id=UNIT, state="occupied", occupant="P-0409", capabilities=o2), 3),
        (Bed(id="L08", unit_id=UNIT, state="clean"), 7),
        (Bed(id="L09", unit_id=UNIT, state="occupied", occupant="P-0431"), 3),
        (Bed(id="L10", unit_id=UNIT, state="occupied", occupant="P-0415"), 3),
        (Bed(id="L11", unit_id=UNIT, state="dirty", capabilities=o2), 26),
        (Bed(id="L12", unit_id=UNIT, state="occupied", occupant="P-0397"), 3),
        (Bed(id="L13", unit_id=UNIT, state="occupied", occupant="P-0425"), 3),
        (Bed(id="L14", unit_id=UNIT, state="closed"), 44),
    ]
    patients: list[tuple[Fact, int]] = [
        (_admitted("P-0371", "L01", hours=96, cleared=None, aval=None), 18),
        (_admitted("P-0412", "L02", hours=140, cleared=True, aval=True), 9),
        (_admitted("P-0402", "L03", hours=50, cleared=None, aval=None), 18),
        (_admitted("P-0420", "L04", hours=72, cleared=True, aval=None), 14),
        (_admitted("P-0388", "L06", hours=120, cleared=True, aval=None), 22),
        (_admitted("P-0409", "L07", hours=30, cleared=None, aval=None), 18),
        (_admitted("P-0431", "L09", hours=88, cleared=None, aval=None), 31),
        (_admitted("P-0415", "L10", hours=60, cleared=None, aval=None), 18),
        (_admitted("P-0397", "L12", hours=160, cleared=True, aval=None), 11),
        (_admitted("P-0425", "L13", hours=20, cleared=None, aval=None), 18),
        (_waiting("U-1049", minutes=402, priority=4, oxygen=True), 5),
        (_waiting("U-1041", minutes=305, priority=3, oxygen=True), 5),
        (_waiting("U-1043", minutes=188, priority=2), 5),
        (_waiting("U-1047", minutes=81, priority=1), 5),
    ]
    logistics: list[tuple[Fact, int]] = [
        (
            Discharge(
                id="P-0412",
                documents_ready=True,
                escort_required=False,
                downstream_required=True,
                downstream_pool_id="smr-nord",
                transport_required=True,
                transport_pool_id="transport-sanitaire",
                transport_requested=False,
            ),
            9,
        ),
        (
            Discharge(
                id="P-0420",
                documents_ready=True,
                escort_required=False,
                downstream_required=False,
                transport_required=False,
            ),
            14,
        ),
        (
            Discharge(
                id="P-0388",
                documents_ready=False,
                escort_required=False,
                downstream_required=False,
                transport_required=True,
                transport_pool_id="transport-sanitaire",
                transport_requested=False,
            ),
            22,
        ),
        (
            Discharge(
                id="P-0397",
                documents_ready=True,
                escort_required=True,
                downstream_required=False,
                transport_required=False,
            ),
            11,
        ),
        (Discharge(id="P-0431", downstream_required=True, downstream_pool_id="smr-nord"), 31),
    ]
    resources: list[tuple[Fact, int]] = [
        (Unit(id=UNIT, staffed_beds=13, cleaning_teams=1), 2),
        (
            ResourcePool(
                id="transport-sanitaire", resource="transport", unit_ids=(UNIT,), available=1
            ),
            6,
        ),
        (ResourcePool(id="smr-nord", resource="downstream", unit_ids=(UNIT,), available=2), 38),
    ]
    return tuple(resources + beds + patients + logistics)


def _events(selected: tuple[tuple[Fact, int], ...], at: datetime) -> tuple[FactEvent, ...]:
    return tuple(
        FactEvent(
            hospital_id=HOSPITAL,
            event_id=f"demo:{fact.kind}:{fact.id}",
            source=SOURCE,
            event_time=at - timedelta(minutes=age),
            available_at=at - timedelta(minutes=age),
            fact=fact,
        )
        for fact, age in selected
    )


def entities(selected: tuple[tuple[Fact, int], ...]) -> tuple[str, ...]:
    return tuple(f"{fact.kind}:{fact.id}" for fact, _ in selected)


def nominal() -> PlanRequest:
    selected = facts()
    return PlanRequest(
        hospital_id=HOSPITAL,
        at=AT,
        expected_entities=entities(selected),
        events=_events(selected, AT),
        assumptions=ASSUMPTIONS,
        horizon_minutes=480,
        scenarios=32,
    )


def perturbations() -> PlanRequest:
    request = nominal()
    return request.model_copy(
        update={
            "future": FutureAssumptions(
                declared_at=AT,
                arrivals=(
                    ArrivalBatch(
                        id="vague-urgences-midi",
                        minute_options=(150, 210, 270),
                        count_options=(1, 2, 3),
                        compatible_units=(UNIT,),
                        priority=2,
                    ),
                ),
                changes=(
                    ResourceChange(
                        id="transport-indisponible",
                        minute=20,
                        resource="transport",
                        target_id="transport-sanitaire",
                        capacity=0,
                    ),
                    ResourceChange(
                        id="transport-retabli",
                        minute=140,
                        resource="transport",
                        target_id="transport-sanitaire",
                        capacity=1,
                    ),
                    ResourceChange(
                        id="bionettoyage-renfort",
                        minute=60,
                        resource="cleaning_teams",
                        target_id=UNIT,
                        capacity=2,
                    ),
                    BedAdmissions(
                        id="L14-reouverture", minute=300, bed_id="L14", admissions_open=True
                    ),
                ),
            )
        }
    )


def incomplete() -> PlanRequest:
    """A missing logistics record and a fact older than the 60 min freshness budget."""
    selected = tuple(
        (fact, 75 if fact.kind == "bed" and fact.id == "L11" else age)
        for fact, age in facts()
        if not (fact.kind == "discharge" and fact.id == "P-0397")
    )
    return PlanRequest(
        hospital_id=HOSPITAL,
        at=AT,
        expected_entities=entities(facts()),
        events=_events(selected, AT),
        assumptions=ASSUMPTIONS,
        horizon_minutes=480,
        scenarios=32,
    )


def live_policy() -> LivePolicy:
    return LivePolicy(hospital_id=HOSPITAL, unit_id=UNIT, sources=(SOURCE,))


def live_batch(at: datetime = AT) -> ObservationBatch:
    selected = facts()
    capacities: tuple[tuple[Resource, str, int, int], ...] = (
        ("staffed", UNIT, 3, 1),
        ("cleaning", UNIT, 1, 1),
        ("transport", "transport-sanitaire", 1, 1),
        ("downstream", "smr-nord", 2, 1),
    )
    return ObservationBatch(
        batch_id="demo-initial",
        hospital_id=HOSPITAL,
        source=SOURCE,
        manifest_version=1,
        expected_entities=entities(selected),
        # The live policy keeps facts for 5 min only: replay them as recently confirmed.
        events=_events(tuple((fact, min(age, 4)) for fact, age in selected), at),
        availability=tuple(
            Availability(
                resource=kind,
                target_id=target,
                available=count,
                source=SOURCE,
                observed_at=at - timedelta(minutes=age),
                evidence_ref=f"demo:{kind}",
            )
            for kind, target, count, age in capacities
        ),
    )
