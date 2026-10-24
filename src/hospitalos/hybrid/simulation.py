"""Closed-cohort discrete-event model. All durations are declared assumptions.

No learned or causal effect is claimed. An action changes allocation/order, not
the sampled service duration. The state supplied here is the observed state.
"""

from __future__ import annotations

import hashlib
import heapq
from collections import defaultdict
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field, StrictInt

from hospitalos.operational.contract import Closed

from .models import Action, State, action_errors, compatible

PositiveMinutes = Annotated[StrictInt, Field(gt=0, le=1440)]


class Assumptions(Closed):
    provenance: Literal["synthetic_hypothesis"] = "synthetic_hypothesis"
    version: str = "closed-cohort-v1"
    cleaning_minutes: Annotated[tuple[PositiveMinutes, ...], Field(min_length=1)] = (30, 60, 90)
    departure_minutes: Annotated[tuple[PositiveMinutes, ...], Field(min_length=1)] = (60, 120, 180)
    # A shared delay regime generates correlated durations across resources.
    load_multipliers: Annotated[tuple[PositiveMinutes, ...], Field(min_length=1)] = (1, 1, 2)


@dataclass(frozen=True)
class Transition:
    minute: int
    kind: str
    patient_id: str | None
    bed_id: str


@dataclass(frozen=True)
class Trajectory:
    horizon_minutes: int
    events: tuple[Transition, ...]


def draw(support: tuple[int, ...], seed: int, scenario: int, mechanism: str, entity: str) -> int:
    """Common innovations indexed by identity, independent of event processing order."""
    key = f"{seed}|{scenario}|{mechanism}|{entity}".encode()
    index = int.from_bytes(hashlib.sha256(key).digest()[:8], "big") % len(support)
    return support[index]


def simulate(
    state: State,
    action: Action,
    assumptions: Assumptions,
    *,
    seed: int,
    scenario: int,
    horizon_minutes: int = 1440,
) -> Trajectory:
    errors = action_errors(state, action)
    if errors:
        raise ValueError(f"Invalid simulation input: {errors}")
    if not 1 <= horizon_minutes <= 1440:
        raise ValueError("Horizon must be between one minute and 24 hours")
    units = {u.id: u for u in state.units}
    beds = {b.id: b for b in state.beds}
    patients = {p.id: p for p in state.patients}
    statuses: dict[str, str] = {b.id: b.state for b in state.beds}
    occupants = {b.id: b.occupant for b in state.beds}
    reservations = {b.id: b.reserved_for for b in state.beds}
    waiting = {p.id for p in state.patients if p.status == "waiting"}
    active_cleaners: dict[str, int] = defaultdict(int)
    dirty_since = {b.id: 0 for b in state.beds if b.state == "dirty"}
    pending: list[tuple[int, str, str, str]] = []
    trace: list[Transition] = []
    multiplier = draw(assumptions.load_multipliers, seed, scenario, "load", state.hospital_id)
    if action.kind == "reserve_bed":
        assert action.bed_id is not None
        reservations[action.bed_id] = action.patient_id
        trace.append(Transition(0, "reserve", action.patient_id, action.bed_id))
    for p in state.patients:
        if (
            p.status == "admitted"
            and p.medically_cleared is True
            and p.downstream_confirmed is True
        ):
            assert p.bed_id is not None
            minute = multiplier * draw(assumptions.departure_minutes, seed, scenario, "exit", p.id)
            heapq.heappush(pending, (minute, "depart", p.bed_id, p.id))

    def allocate(minute: int) -> None:
        reserved_patients = {p for p in reservations.values() if p is not None}
        for patient_id in sorted(
            waiting, key=lambda key: (-patients[key].priority, patients[key].waiting_since, key)
        ):
            p = patients[patient_id]
            for bed_id, bed in sorted(beds.items()):
                if statuses[bed_id] != "clean" or not compatible(p, bed):
                    continue
                if reservations[bed_id] not in (None, patient_id):
                    continue
                if patient_id in reserved_patients and reservations[bed_id] != patient_id:
                    continue
                occupied = sum(
                    b.unit_id == bed.unit_id and occupants[b.id] is not None for b in beds.values()
                )
                # Keep capacity committed to other reservations in this unit.
                other_reservations = sum(
                    b.unit_id == bed.unit_id and reservations[b.id] not in (None, patient_id)
                    for b in beds.values()
                )
                cap = units[bed.unit_id].staffed_beds
                if cap is None or occupied + other_reservations >= cap:
                    continue
                statuses[bed_id] = "occupied"
                occupants[bed_id] = patient_id
                reservations[bed_id] = None
                waiting.remove(patient_id)
                trace.append(Transition(minute, "admit", patient_id, bed_id))
                break

    def start_cleaning(minute: int) -> None:
        for unit_id, unit in sorted(units.items()):
            dirty = [b for b in beds if beds[b].unit_id == unit_id and statuses[b] == "dirty"]
            dirty.sort(
                key=lambda b: (
                    0 if action.kind == "prioritize_cleaning" and action.bed_id == b else 1,
                    dirty_since[b],
                    b,
                )
            )
            for bed_id in dirty:
                if active_cleaners[unit_id] >= (unit.cleaning_teams or 0):
                    break
                statuses[bed_id] = "cleaning"
                active_cleaners[unit_id] += 1
                duration = multiplier * draw(
                    assumptions.cleaning_minutes, seed, scenario, "clean", bed_id
                )
                trace.append(Transition(minute, "clean_start", None, bed_id))
                heapq.heappush(pending, (minute + duration, "clean_end", bed_id, ""))

    allocate(0)
    start_cleaning(0)
    while pending and pending[0][0] <= horizon_minutes:
        minute = pending[0][0]
        batch = []
        while pending and pending[0][0] == minute:
            batch.append(heapq.heappop(pending))
        for _time, kind, bed_id, patient_id in batch:
            if kind == "depart":
                if occupants[bed_id] != patient_id:
                    raise ValueError("Departure identity mismatch")
                occupants[bed_id] = None
                statuses[bed_id] = "dirty"
                dirty_since[bed_id] = minute
            else:
                statuses[bed_id] = "clean"
                active_cleaners[beds[bed_id].unit_id] -= 1
            trace.append(Transition(minute, kind, patient_id or None, bed_id))
        allocate(minute)
        start_cleaning(minute)
    return Trajectory(horizon_minutes, tuple(trace))
