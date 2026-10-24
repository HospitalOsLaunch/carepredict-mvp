"""Discrete-event model with explicit synthetic arrivals and perturbations.

No causal effect is claimed. An action changes allocation/order, not
the sampled service duration. The state supplied here is the observed state.
"""

from __future__ import annotations

import heapq
from collections import defaultdict
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field, StrictInt

from hospitalos.operational.contract import Closed

from .innovations import draw as draw
from .models import Action, State, action_errors, compatible, discharge_blockers
from .preparation import PreparationForecasts, preparation_draw, validate_preparation
from .scenarios import BedAdmissions, FutureArrival, FutureTape, ResourceChange, validate_tape

PositiveMinutes = Annotated[StrictInt, Field(gt=0, le=1440)]


class Assumptions(Closed):
    provenance: Literal["synthetic_hypothesis"] = "synthetic_hypothesis"
    version: Literal["release-allocate-v2"] = "release-allocate-v2"
    cleaning_minutes: Annotated[tuple[PositiveMinutes, ...], Field(min_length=1)] = (30, 60, 90)
    departure_minutes: Annotated[tuple[PositiveMinutes, ...], Field(min_length=1)] = (60, 120, 180)
    transport_minutes: Annotated[tuple[PositiveMinutes, ...], Field(min_length=1)] = (30, 60, 90)
    transport_return_minutes: Annotated[tuple[PositiveMinutes, ...], Field(min_length=1)] = (30, 60)
    # A shared delay regime generates correlated durations across resources.
    load_multipliers: Annotated[tuple[PositiveMinutes, ...], Field(min_length=1)] = (1, 1, 2)


@dataclass(frozen=True)
class Transition:
    minute: int
    kind: str
    patient_id: str | None
    bed_id: str
    resource_id: str | None = None
    external_id: str | None = None


@dataclass(frozen=True)
class Trajectory:
    horizon_minutes: int
    events: tuple[Transition, ...]


def simulate(
    state: State,
    action: Action,
    assumptions: Assumptions,
    *,
    seed: int,
    scenario: int,
    horizon_minutes: int = 1440,
    future: FutureTape | None = None,
    preparation: PreparationForecasts | None = None,
) -> Trajectory:
    errors = action_errors(state, action)
    if errors:
        raise ValueError(f"Invalid simulation input: {errors}")
    if not 1 <= horizon_minutes <= 1440:
        raise ValueError("Horizon must be between one minute and 24 hours")
    future = future or FutureTape(state.at, ())
    validate_tape(state, future)
    if preparation is not None:
        validate_preparation(state, preparation)
    curves = {c.patient_id: c for c in preparation.curves} if preparation is not None else {}
    units = {u.id: u for u in state.units}
    beds = {b.id: b for b in state.beds}
    patients = {p.id: p for p in state.patients}
    statuses: dict[str, str] = {b.id: b.state for b in state.beds}
    blocked_beds = {b.id for b in state.beds if b.state == "closed"}
    occupants = {b.id: b.occupant for b in state.beds}
    reservations = {b.id: b.reserved_for for b in state.beds}
    waiting = {p.id for p in state.patients if p.status == "waiting"}
    active_cleaners: dict[str, int] = defaultdict(int)
    pools = {p.id: p for p in state.pools}
    logistics = {d.id: d for d in state.discharges}
    downstream_limits = {p.id: p.available or 0 for p in state.pools if p.resource == "downstream"}
    downstream_committed: dict[str, int] = defaultdict(int)
    transport_active: dict[str, int] = defaultdict(int)
    departure_ready: dict[str, int] = {}
    dirty_since = {b.id: 0 for b in state.beds if b.state == "dirty"}
    pending: list[tuple[int, str, str, str]] = []
    trace: list[Transition] = []
    future_events = {e.id: e for e in future.events}
    for e in future.events:
        heapq.heappush(pending, (e.minute, "__future", e.id, ""))
    multiplier = draw(assumptions.load_multipliers, seed, scenario, "load", state.hospital_id)
    if action.kind == "reserve_bed":
        assert action.bed_id is not None
        reservations[action.bed_id] = action.patient_id
        trace.append(Transition(0, "reserve", action.patient_id, action.bed_id))
    if action.kind == "request_transport":
        assert action.patient_id is not None and action.bed_id is not None
        trace.append(
            Transition(
                0,
                "request_transport",
                action.patient_id,
                action.bed_id,
                logistics[action.patient_id].transport_pool_id,
            )
        )
    for p in state.patients:
        new_request = action.kind == "request_transport" and action.patient_id == p.id
        if not discharge_blockers(
            state, p, include_request=not new_request, require_capacity=False
        ):
            assert p.bed_id is not None
            minute = (
                preparation_draw(
                    curves[p.id],
                    seed,
                    scenario,
                    shared_loading=preparation.shared_loading,
                    hospital_id=state.hospital_id,
                )
                if preparation is not None
                else multiplier * draw(assumptions.departure_minutes, seed, scenario, "exit", p.id)
            )
            if minute is not None:
                heapq.heappush(pending, (minute, "departure_ready", p.bed_id, p.id))

    def depart(minute: int, bed_id: str, patient_id: str) -> None:
        if occupants[bed_id] != patient_id:
            raise ValueError("Departure identity mismatch")
        occupants[bed_id] = None
        statuses[bed_id] = "dirty"
        dirty_since[bed_id] = minute
        trace.append(Transition(minute, "depart", patient_id, bed_id))

    def start_departures(minute: int) -> None:
        # A place is reserved only when all other resources can start serving the patient.
        for patient_id in sorted(
            departure_ready, key=lambda p: (departure_ready[p], -patients[p].priority, p)
        ):
            p, d = patients[patient_id], logistics[patient_id]
            assert p.bed_id is not None
            if (
                d.downstream_required
                and downstream_committed[d.downstream_pool_id or ""]
                >= downstream_limits[d.downstream_pool_id or ""]
            ):
                continue
            if d.transport_required:
                assert d.transport_pool_id is not None
                if transport_active[d.transport_pool_id] >= (
                    pools[d.transport_pool_id].available or 0
                ):
                    continue
            if d.downstream_required:
                assert d.downstream_pool_id is not None
                downstream_committed[d.downstream_pool_id] += 1
                trace.append(
                    Transition(
                        minute, "downstream_reserve", patient_id, p.bed_id, d.downstream_pool_id
                    )
                )
            del departure_ready[patient_id]
            if d.transport_required:
                assert d.transport_pool_id is not None
                transport_active[d.transport_pool_id] += 1
                duration = multiplier * draw(
                    assumptions.transport_minutes, seed, scenario, "transport", patient_id
                )
                trace.append(
                    Transition(minute, "transport_start", patient_id, p.bed_id, d.transport_pool_id)
                )
                heapq.heappush(
                    pending, (minute + duration, "transport_depart", p.bed_id, patient_id)
                )
            else:
                depart(minute, p.bed_id, patient_id)

    def allocate(minute: int) -> None:
        reserved_patients = {p for p in reservations.values() if p is not None}
        for patient_id in sorted(
            waiting, key=lambda key: (-patients[key].priority, patients[key].waiting_since, key)
        ):
            p = patients[patient_id]
            for bed_id, bed in sorted(beds.items()):
                if bed_id in blocked_beds or statuses[bed_id] != "clean" or not compatible(p, bed):
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
            dirty = [
                b
                for b in beds
                if beds[b].unit_id == unit_id and statuses[b] == "dirty" and b not in blocked_beds
            ]
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

    def reconcile_reservations(minute: int) -> None:
        # Remove commitments invalidated by a closure/capacity drop; never remove patients.
        def priority(bed_id: str) -> tuple[int, str]:
            patient = patients.get(reservations[bed_id] or "")
            return (patient.priority if patient else 0, bed_id)

        for bed_id in sorted(beds, key=priority):
            patient_id = reservations[bed_id]
            if patient_id is None:
                continue
            unit_id = beds[bed_id].unit_id
            committed = sum(
                b.unit_id == unit_id
                and (occupants[b.id] is not None or reservations[b.id] is not None)
                for b in beds.values()
            )
            if bed_id in blocked_beds or committed > (units[unit_id].staffed_beds or 0):
                reservations[bed_id] = None
                trace.append(Transition(minute, "reservation_cancel", patient_id, bed_id))

    allocate(0)
    start_cleaning(0)
    while pending and pending[0][0] <= horizon_minutes:
        minute = pending[0][0]
        batch = []
        while pending and pending[0][0] == minute:
            batch.append(heapq.heappop(pending))
        # All declared external events precede completions/new starts at the same time.
        for _time, kind, key, _patient_id in batch:
            if kind != "__future":
                continue
            e = future_events[key]
            if isinstance(e, FutureArrival):
                patients[e.patient.id] = e.patient
                waiting.add(e.patient.id)
                trace.append(Transition(minute, "arrival", e.patient.id, "", external_id=e.id))
            elif isinstance(e, ResourceChange):
                if e.resource in {"staffed_beds", "cleaning_teams"}:
                    units[e.target_id] = units[e.target_id].model_copy(
                        update={e.resource: e.capacity}
                    )
                else:
                    pools[e.target_id] = pools[e.target_id].model_copy(
                        update={"available": e.capacity}
                    )
                    if e.resource == "downstream":
                        downstream_limits[e.target_id] = e.capacity
                trace.append(
                    Transition(
                        minute,
                        "resource_change",
                        None,
                        "",
                        resource_id=e.target_id,
                        external_id=e.id,
                    )
                )
            elif isinstance(e, BedAdmissions):
                if e.admissions_open:
                    blocked_beds.discard(e.bed_id)
                    if statuses[e.bed_id] == "closed":
                        statuses[e.bed_id] = "dirty"
                        dirty_since[e.bed_id] = minute
                else:
                    blocked_beds.add(e.bed_id)
                trace.append(Transition(minute, "bed_admissions", None, e.bed_id, external_id=e.id))
        for _time, kind, bed_id, patient_id in batch:
            if kind == "__future":
                continue
            if kind == "departure_ready":
                departure_ready[patient_id] = minute
                trace.append(Transition(minute, kind, patient_id, bed_id))
            elif kind == "transport_depart":
                resource_id = logistics[patient_id].transport_pool_id
                assert resource_id is not None
                trace.append(Transition(minute, kind, patient_id, bed_id, resource_id))
                depart(minute, bed_id, patient_id)
                return_delay = multiplier * draw(
                    assumptions.transport_return_minutes,
                    seed,
                    scenario,
                    "transport_return",
                    patient_id,
                )
                heapq.heappush(
                    pending, (minute + return_delay, "transport_end", bed_id, patient_id)
                )
            elif kind == "transport_end":
                resource_id = logistics[patient_id].transport_pool_id
                assert resource_id is not None
                transport_active[resource_id] -= 1
                trace.append(Transition(minute, kind, patient_id, bed_id, resource_id))
            elif kind == "clean_end":
                statuses[bed_id] = "clean"
                active_cleaners[beds[bed_id].unit_id] -= 1
                trace.append(Transition(minute, kind, None, bed_id))
            else:
                raise ValueError("Unknown scheduled event")
        start_departures(minute)
        reconcile_reservations(minute)
        allocate(minute)
        start_cleaning(minute)
    return Trajectory(horizon_minutes, tuple(trace))
