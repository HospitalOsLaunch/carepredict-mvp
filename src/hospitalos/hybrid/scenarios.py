"""Declared synthetic futures, separate from observations and immediate actions.

Arrival supports are hypotheses, not a fitted arrival process. A sampled tape is
immutable and shared between decisions; the scorer receives it independently.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator

from hospitalos.operational.contract import Closed, Identifier, instant

from .innovations import draw
from .models import Patient, State

Minute = Annotated[StrictInt, Field(ge=1, le=1440)]
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
        return FutureTape(state.at, ())
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
    tape = FutureTape(
        specification.declared_at, tuple(sorted(events, key=lambda e: (e.minute, e.id)))
    )
    validate_tape(state, tape)
    return tape
