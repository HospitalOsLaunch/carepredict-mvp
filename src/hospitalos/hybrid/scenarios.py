"""Declared synthetic futures, separate from observations and immediate actions.

Arrival supports are hypotheses, not a fitted arrival process. A sampled tape is
immutable and shared between decisions; the scorer receives it independently.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import accumulate
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator

from hospitalos.operational.contract import Closed, Identifier, instant

from .innovations import draw, uniform
from .models import Action, Patient, State
from .outlook import Roster, latest

Minute = Annotated[StrictInt, Field(ge=1, le=10080)]
Capacity = Annotated[StrictInt, Field(ge=0, le=1000)]


class ArrivalBatch(Closed):
    id: Identifier
    minute_options: Annotated[tuple[Minute, ...], Field(min_length=1, max_length=64)]
    count_options: Annotated[
        tuple[Annotated[StrictInt, Field(ge=0, le=20)], ...], Field(min_length=1, max_length=64)
    ]
    compatible_units: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    requirements: tuple[Identifier, ...] = ()
    priority: Annotated[StrictInt, Field(ge=1, le=5)] = 1


class ResourceChange(Closed):
    kind: Literal["resource_change"] = "resource_change"
    id: Identifier
    minute: Minute
    resource: Literal["staffed_beds", "cleaning_teams", "transport", "downstream"]
    target_id: Identifier
    capacity: Capacity


class BedAdmissions(Closed):
    kind: Literal["bed_admissions"] = "bed_admissions"
    id: Identifier
    minute: Minute
    bed_id: Identifier
    admissions_open: StrictBool


Change = Annotated[ResourceChange | BedAdmissions, Field(discriminator="kind")]


class FutureAssumptions(Closed):
    schema_version: Literal["HYBRID_FUTURE_1"] = "HYBRID_FUTURE_1"
    provenance: Literal["synthetic_hypothesis"] = "synthetic_hypothesis"
    declared_at: datetime
    arrivals: Annotated[tuple[ArrivalBatch, ...], Field(max_length=32)] = ()
    changes: Annotated[tuple[Change, ...], Field(max_length=128)] = ()

    @field_validator("declared_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return instant(value)

    @model_validator(mode="after")
    def identities_and_budget(self) -> Self:
        ids = [a.id for a in self.arrivals] + [c.id for c in self.changes]
        if len(ids) != len(set(ids)):
            raise ValueError("Scenario component identities must be unique")
        if sum(max(a.count_options) for a in self.arrivals) > 200:
            raise ValueError("At most 200 future arrivals per scenario")
        slots = [
            (c.minute, c.kind, c.resource, c.target_id)
            if isinstance(c, ResourceChange)
            else (c.minute, c.kind, "bed", c.bed_id)
            for c in self.changes
        ]
        if len(slots) != len(set(slots)):
            raise ValueError("Conflicting changes to the same resource and time")
        return self


class FutureArrival(Closed):
    kind: Literal["arrival"] = "arrival"
    id: Identifier
    minute: Minute
    patient: Patient


ExternalEvent = FutureArrival | ResourceChange | BedAdmissions


@dataclass(frozen=True)
class FutureTape:
    declared_at: datetime
    events: tuple[ExternalEvent, ...]


def validate_tape(state: State, tape: FutureTape) -> None:
    if instant(tape.declared_at) > state.at:
        raise ValueError("Scenario assumptions were not declared at the decision origin")
    units = {u.id for u in state.units}
    pools = {p.id: p for p in state.pools}
    beds = {b.id for b in state.beds}
    patients = {p.id for p in state.patients}
    ids: set[str] = set()
    slots: set[tuple[int, str, str]] = set()
    for event in tape.events:
        if event.id in ids:
            raise ValueError("Duplicate external event")
        ids.add(event.id)
        if isinstance(event, FutureArrival):
            p = event.patient
            if (
                p.id in patients
                or p.status != "waiting"
                or p.medically_cleared is not None
                or p.downstream_confirmed is not None
                or p.bed_id is not None
                or p.waiting_since != state.at + timedelta(minutes=event.minute)
                or not p.compatible_units
                or not set(p.compatible_units) <= units
            ):
                raise ValueError("Invalid future arrival identity, timing or scope")
            patients.add(p.id)
        elif isinstance(event, ResourceChange):
            if event.resource in {"staffed_beds", "cleaning_teams"}:
                if event.target_id not in units:
                    raise ValueError("Unknown future unit")
            elif event.target_id not in pools or pools[event.target_id].resource != event.resource:
                raise ValueError("Unknown or mismatched future pool")
            key: tuple[int, str, str] = (event.minute, event.resource, event.target_id)
            if key in slots:
                raise ValueError("Conflicting resource changes")
            slots.add(key)
        else:
            if event.bed_id not in beds:
                raise ValueError("Unknown future bed")
            key = (event.minute, "bed", event.bed_id)
            if key in slots:
                raise ValueError("Conflicting bed changes")
            slots.add(key)


def sample_future(
    state: State, specification: FutureAssumptions | None, seed: int, scenario: int
) -> FutureTape:
    if specification is None:
        specification = FutureAssumptions(declared_at=state.at)
    if specification.declared_at > state.at:
        raise ValueError("Future assumptions cannot be learned after the decision origin")
    units = {u.id for u in state.units}
    events: list[ExternalEvent] = list(specification.changes)
    for batch in specification.arrivals:
        if not set(batch.compatible_units) <= units:
            raise ValueError("Unknown arrival unit even when a zero count is drawn")
        minute = draw(batch.minute_options, seed, scenario, "arrival_time", batch.id)
        count = draw(batch.count_options, seed, scenario, "arrival_count", batch.id)
        for ordinal in range(count):
            identity = hashlib.sha256(f"{batch.id}:{ordinal}".encode()).hexdigest()[:32]
            patient_id = f"hypothetical:{identity}"
            events.append(
                FutureArrival(
                    id=f"arrival:{identity}",
                    minute=minute,
                    patient=Patient(
                        id=patient_id,
                        status="waiting",
                        compatible_units=batch.compatible_units,
                        requirements=batch.requirements,
                        priority=batch.priority,
                        waiting_since=state.at + timedelta(minutes=minute),
                    ),
                )
            )
    for schedule in state.schedules:
        for booking in schedule.admissions:
            req = booking.request
            if (
                booking.status != "booked"
                or req.expected_arrival <= state.at
                or any(p.id == req.request_id for p in state.patients)
            ):
                continue
            dist = req.arrival_delay
            u = uniform(seed, scenario, "booked_arrival", req.request_id) * sum(dist.weights)
            delay = next(
                v for v, cut in zip(dist.support, accumulate(dist.weights), strict=True) if u < cut
            )
            minute = math.ceil((req.expected_arrival - state.at).total_seconds() / 60) + 60 * delay
            if minute <= 10080:
                events.append(
                    FutureArrival(
                        id=f"booked:{req.request_id}",
                        minute=minute,
                        patient=Patient(
                            id=req.request_id,
                            status="waiting",
                            compatible_units=(schedule.id,),
                            requirements=req.requirements,
                            waiting_since=state.at + timedelta(minutes=minute),
                        ),
                    )
                )
    tape = FutureTape(
        specification.declared_at, tuple(sorted(events, key=lambda e: (e.minute, e.id)))
    )
    validate_tape(state, tape)
    return tape


def staffing_tape(
    state: State, tape: FutureTape, actions: tuple[Action, ...]
) -> tuple[State, FutureTape]:
    """Overlay observable commitments and the proposed staff on the paired capacity tape."""
    selected = {a.slot_id for a in actions if a.kind == "reinforce"}
    events = list(tape.events)
    units = {u.id: u for u in state.units}
    for schedule in state.schedules:
        offers = [
            o
            for o in schedule.offers
            if not o.included_in_baseline and (o.committed or o.option.option_id in selected)
        ]
        if not offers:
            continue
        unit = units[schedule.id]
        base = unit.staffed_beds
        if base is None:
            raise ValueError("Unobserved staff capacity")
        changes = {
            e.minute: e
            for e in events
            if isinstance(e, ResourceChange)
            and e.resource == "staffed_beds"
            and e.target_id == unit.id
        }
        events = [e for e in events if e not in changes.values()]
        intervals: list[tuple[int, int, int]] = []
        roster, _ = latest(state, unit.id, "roster")
        for offer in offers:
            start = math.ceil((offer.option.start - state.at).total_seconds() / 60)
            stop = math.floor((offer.option.end - state.at).total_seconds() / 60)
            # A committed person already on the roster adds no second place.
            included = (
                [
                    (
                        max(start, math.floor((s.start - state.at).total_seconds() / 60)),
                        min(stop, math.ceil((s.end - state.at).total_seconds() / 60)),
                    )
                    for s in roster.shifts
                    if offer.committed
                    and s.staff_id == offer.staff_id
                    and s.start < offer.option.end
                    and offer.option.start < s.end
                ]
                if isinstance(roster, Roster)
                else []
            )
            cuts = sorted({start, stop} | {v for lo, hi in included for v in (lo, hi)})
            intervals.extend(
                (lo, hi, offer.staffed_places)
                for lo, hi in zip(cuts, cuts[1:], strict=False)
                if not any(a <= lo < b for a, b in included)
            )
        boundaries = set(changes) | {t for start, stop, _ in intervals for t in (start, stop)}

        def extra(minute: int, periods: list[tuple[int, int, int]] = intervals) -> int:
            return sum(n for start, end, n in periods if start <= minute < end)

        units[unit.id] = unit.model_copy(update={"staffed_beds": base + extra(0)})
        for minute in sorted(t for t in boundaries if 0 < t <= 10080):
            if minute in changes:
                base = changes[minute].capacity
            events.append(
                ResourceChange(
                    id=f"staff:{unit.id}:{minute}",
                    minute=minute,
                    target_id=unit.id,
                    resource="staffed_beds",
                    capacity=base + extra(minute),
                )
            )
    return state.model_copy(update={"units": tuple(units.values())}), FutureTape(
        tape.declared_at, tuple(sorted(events, key=lambda e: (e.minute, e.id)))
    )


def booking_setup(
    state: State, actions: tuple[Action, ...], tape: FutureTape
) -> dict[str, tuple[int, str | None, int, int]]:
    """Arrived demand stays in the queue during setup; preparation only speeds a compatible slot."""
    prepared = {a.slot_id: a.bed_id for a in actions if a.kind == "prepare_admission"}
    arrivals = {e.patient.id: e.minute for e in tape.events if isinstance(e, FutureArrival)}
    setup: dict[str, tuple[int, str | None, int, int]] = {}
    for schedule in state.schedules:
        for booking in schedule.admissions:
            req = booking.request
            if req.request_id in arrivals:
                setup[req.request_id] = (
                    arrivals[req.request_id] + req.admission_task_minutes,
                    booking.prepared_bed or prepared.get(req.request_id),
                    math.ceil((booking.window_start - state.at).total_seconds() / 60),
                    math.ceil((booking.window_end - state.at).total_seconds() / 60),
                )
    return setup


def slot_ready(
    setup: dict[str, tuple[int, str | None, int, int]], patient: str, bed: str, minute: int
) -> bool:
    hold = setup.get(patient)
    return not hold or minute >= hold[0] or (bed == hold[1] and hold[2] <= minute < hold[3])
