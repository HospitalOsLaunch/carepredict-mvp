"""Independent event-log scorer; does not call the transition generator."""

from __future__ import annotations

from dataclasses import dataclass

from .models import Patient, State, compatible
from .scenarios import BedAdmissions, FutureArrival, FutureTape, ResourceChange, validate_tape
from .simulation import Trajectory, Transition


@dataclass(frozen=True)
class ResourcePressure:
    staffed_patient_minutes: int = 0
    cleaning_team_minutes: int = 0
    transport_team_minutes: int = 0
    downstream_place_minutes: int = 0

    def components(self) -> tuple[int, int, int, int]:
        return (
            self.staffed_patient_minutes,
            self.cleaning_team_minutes,
            self.transport_team_minutes,
            self.downstream_place_minutes,
        )


@dataclass(frozen=True)
class Score:
    waiting_patient_minutes: int
    admitted: int
    waiting_at_end: int
    violations: tuple[str, ...]
    arrived: int = 0
    cancelled_reservations: int = 0
    pressure: ResourcePressure = ResourcePressure()


def score(
    state: State, trajectory: Trajectory, *, expected_future: FutureTape | None = None
) -> Score:
    expected_future = expected_future or FutureTape(state.at, ())
    validate_tape(state, expected_future)
    expected = {e.id: e for e in expected_future.events if e.minute <= trajectory.horizon_minutes}
    seen: set[str] = set()
    beds = {b.id: b for b in state.beds}
    patients = {p.id: p for p in state.patients}
    units = {u.id: u for u in state.units}
    occupants = {b.id: b.occupant for b in state.beds}
    status: dict[str, str] = {b.id: b.state for b in state.beds}
    blocked_beds = {b.id for b in state.beds if b.state == "closed"}
    reservations = {b.id: b.reserved_for for b in state.beds}
    waiting = {p.id for p in state.patients if p.status == "waiting"}
    departed = {p.id for p in state.patients if p.status == "departed"}
    discharges = {d.id: d for d in state.discharges}
    pools = {p.id: p for p in state.pools}
    requested = {d.id for d in state.discharges if d.transport_requested is True}
    ready: set[str] = set()
    downstream_reserved: set[str] = set()
    downstream_limits = {r.id: r.available or 0 for r in state.pools if r.resource == "downstream"}
    committed = {r.id: 0 for r in state.pools if r.resource == "downstream"}
    transports: dict[str, tuple[str, int]] = {}
    transported: dict[str, int] = {}
    admitted, area, clock = 0, 0, 0
    arrived, cancelled = 0, 0
    exposure = [0, 0, 0, 0]
    violations: list[str] = ["invalid_initial_state"] if state.issues else []

    def logistics_valid(p: Patient, *, require_request: bool = True) -> bool:
        # Intentionally reconstruct the contract here, without the planner's gate helper.
        d = discharges.get(p.id)
        if d is None or p.medically_cleared is not True or d.documents_ready is not True:
            return False
        if d.escort_required is None or (d.escort_required and d.escort_confirmed is not True):
            return False
        if d.transport_required is None or d.downstream_required is None:
            return False
        for kind, required, pool_id in (
            ("transport", d.transport_required, d.transport_pool_id),
            ("downstream", d.downstream_required, d.downstream_pool_id),
        ):
            if required:
                pool = pools.get(pool_id or "")
                bed = beds.get(p.bed_id or "")
                if (
                    pool is None
                    or pool.resource != kind
                    or pool.available is None
                    or bed is None
                    or bed.unit_id not in pool.unit_ids
                ):
                    return False
        if d.downstream_required and p.downstream_confirmed is not True:
            return False
        return not (require_request and d.transport_required and p.id not in requested)

    def integrate_pressure(duration: int) -> None:
        levels = (
            sum(
                max(
                    0,
                    sum(b.unit_id == u.id and occupants[b.id] is not None for b in beds.values())
                    - (u.staffed_beds or 0),
                )
                for u in units.values()
            ),
            sum(
                max(
                    0,
                    sum(b.unit_id == u.id and status[b.id] == "cleaning" for b in beds.values())
                    - (u.cleaning_teams or 0),
                )
                for u in units.values()
            ),
            sum(
                max(
                    0,
                    sum(pool_id == r.id for pool_id, _ in transports.values()) - (r.available or 0),
                )
                for r in pools.values()
                if r.resource == "transport"
            ),
            sum(max(0, committed[key] - limit) for key, limit in downstream_limits.items()),
        )
        for index, level in enumerate(levels):
            exposure[index] += duration * level

    for event in trajectory.events:
        if not clock <= event.minute <= trajectory.horizon_minutes:
            violations.append("event_time")
            continue
        area += len(waiting) * (event.minute - clock)
        integrate_pressure(event.minute - clock)
        clock = event.minute
        if event.kind in {"arrival", "resource_change", "bed_admissions"}:
            external = expected.get(event.external_id or "")
            if (
                external is None
                or external.id in seen
                or external.minute != event.minute
                or external.kind != event.kind
            ):
                violations.append("invalid_external_event")
                continue
            if isinstance(external, FutureArrival):
                expected_trace = Transition(
                    external.minute, "arrival", external.patient.id, "", external_id=external.id
                )
            elif isinstance(external, ResourceChange):
                expected_trace = Transition(
                    external.minute,
                    "resource_change",
                    None,
                    "",
                    resource_id=external.target_id,
                    external_id=external.id,
                )
            else:
                expected_trace = Transition(
                    external.minute,
                    "bed_admissions",
                    None,
                    external.bed_id,
                    external_id=external.id,
                )
            if event != expected_trace:
                violations.append("external_payload_mismatch")
                continue
            seen.add(external.id)
            if isinstance(external, FutureArrival):
                patients[external.patient.id] = external.patient
                waiting.add(external.patient.id)
                arrived += 1
            elif isinstance(external, ResourceChange):
                if external.resource in {"staffed_beds", "cleaning_teams"}:
                    units[external.target_id] = units[external.target_id].model_copy(
                        update={external.resource: external.capacity}
                    )
                else:
                    pools[external.target_id] = pools[external.target_id].model_copy(
                        update={"available": external.capacity}
                    )
                    if external.resource == "downstream":
                        downstream_limits[external.target_id] = external.capacity
            elif isinstance(external, BedAdmissions):
                if external.admissions_open:
                    blocked_beds.discard(external.bed_id)
                    if status[external.bed_id] == "closed":
                        status[external.bed_id] = "dirty"
                else:
                    blocked_beds.add(external.bed_id)
            continue
        if event.external_id is not None:
            violations.append("unexpected_external_identity")
        if any(e.minute <= event.minute and e.id not in seen for e in expected.values()):
            violations.append("external_event_missing_or_late")
        if event.bed_id not in beds:
            violations.append("unknown_bed")
            continue
        bed_id = event.bed_id
        if event.kind in {
            "request_transport",
            "departure_ready",
            "downstream_reserve",
            "transport_start",
            "transport_depart",
        }:
            p = patients.get(event.patient_id or "")
            if (
                p is None
                or occupants[bed_id] != p.id
                or p.bed_id != bed_id
                or not logistics_valid(p, require_request=event.kind != "request_transport")
            ):
                violations.append("invalid_release_prerequisites")
                continue
            d = discharges[p.id]
            if event.kind == "request_transport":
                if (
                    event.minute != 0
                    or d.transport_required is not True
                    or d.transport_requested is not False
                    or p.id in requested
                    or event.resource_id != d.transport_pool_id
                    or any(
                        pools[key].available == 0
                        for key in (d.transport_pool_id, d.downstream_pool_id)
                        if key is not None
                    )
                ):
                    violations.append("invalid_transport_request")
                    continue
                requested.add(p.id)
            elif event.kind == "departure_ready":
                if p.id in ready or event.minute <= 0:
                    violations.append("invalid_departure_readiness")
                    continue
                ready.add(p.id)
            elif event.kind == "downstream_reserve":
                if (
                    p.id not in ready
                    or not d.downstream_required
                    or event.resource_id != d.downstream_pool_id
                    or p.id in downstream_reserved
                ):
                    violations.append("invalid_downstream_reservation")
                    continue
                assert d.downstream_pool_id is not None
                if committed[d.downstream_pool_id] >= downstream_limits[d.downstream_pool_id]:
                    violations.append("downstream_capacity")
                    continue
                committed[d.downstream_pool_id] += 1
                downstream_reserved.add(p.id)
            elif event.kind == "transport_start":
                if (
                    p.id not in ready
                    or not d.transport_required
                    or event.resource_id != d.transport_pool_id
                    or p.id in transports
                    or p.id in transported
                    or (d.downstream_required and p.id not in downstream_reserved)
                ):
                    violations.append("invalid_transport_start")
                    continue
                assert d.transport_pool_id is not None
                active = sum(resource == d.transport_pool_id for resource, _ in transports.values())
                if active >= (pools[d.transport_pool_id].available or 0):
                    violations.append("transport_capacity")
                    continue
                transports[p.id] = (d.transport_pool_id, event.minute)
            else:
                running = transports.get(p.id)
                if (
                    running is None
                    or running[0] != event.resource_id
                    or event.minute <= running[1]
                    or p.id in transported
                ):
                    violations.append("invalid_transport_depart")
                    continue
                transported[p.id] = event.minute
        elif event.kind == "transport_end":
            p = patients.get(event.patient_id or "")
            running = transports.get(event.patient_id or "")
            departed_at = transported.get(event.patient_id or "")
            if (
                p is None
                or p.bed_id != bed_id
                or p.id not in departed
                or running is None
                or running[0] != event.resource_id
                or departed_at is None
                or event.minute <= departed_at
            ):
                violations.append("invalid_transport_end")
                continue
            del transports[p.id]
        elif event.kind == "reservation_cancel":
            unit = units[beds[bed_id].unit_id]
            commitments = sum(
                b.unit_id == unit.id
                and (occupants[b.id] is not None or reservations[b.id] is not None)
                for b in beds.values()
            )
            if (
                event.patient_id is None
                or reservations[bed_id] != event.patient_id
                or (bed_id not in blocked_beds and commitments <= (unit.staffed_beds or 0))
            ):
                violations.append("invalid_reservation_cancellation")
                continue
            reservations[bed_id] = None
            cancelled += 1
        elif event.kind == "reserve":
            p = patients.get(event.patient_id or "")
            if (
                p is None
                or p.id not in waiting
                or status[bed_id] != "clean"
                or bed_id in blocked_beds
                or reservations[bed_id] is not None
                or p.id in reservations.values()
                or not compatible(p, beds[bed_id])
            ):
                violations.append("invalid_reservation")
                continue
            unit = units[beds[bed_id].unit_id]
            commitments = sum(
                b.unit_id == unit.id
                and (occupants[b.id] is not None or reservations[b.id] is not None)
                for b in beds.values()
            )
            if unit.staffed_beds is None or commitments >= unit.staffed_beds:
                violations.append("reservation_capacity")
            reservations[bed_id] = p.id
        elif event.kind == "depart":
            p = patients.get(event.patient_id or "")
            if (
                p is None
                or occupants[bed_id] != p.id
                or p.id not in ready
                or not logistics_valid(p)
            ):
                violations.append("invalid_departure")
                continue
            d = discharges[p.id]
            if (d.downstream_required and p.id not in downstream_reserved) or (
                d.transport_required and p.id not in transported
            ):
                violations.append("incomplete_departure_logistics")
                continue
            departed.add(p.id)
            ready.remove(p.id)
            occupants[bed_id] = None
            status[bed_id] = "dirty"
        elif event.kind == "clean_start":
            if status[bed_id] != "dirty" or bed_id in blocked_beds:
                violations.append("invalid_clean_start")
            status[bed_id] = "cleaning"
            unit = units[beds[bed_id].unit_id]
            active = sum(b.unit_id == unit.id and status[b.id] == "cleaning" for b in beds.values())
            if active > (unit.cleaning_teams or 0):
                violations.append("cleaner_capacity")
        elif event.kind == "clean_end":
            if status[bed_id] != "cleaning":
                violations.append("invalid_clean_end")
            status[bed_id] = "clean"
        elif event.kind == "admit":
            p = patients.get(event.patient_id or "")
            if (
                p is None
                or p.id not in waiting
                or status[bed_id] != "clean"
                or bed_id in blocked_beds
                or occupants[bed_id] is not None
                or not compatible(p, beds[bed_id])
                or reservations[bed_id] not in (None, p.id)
                or (p.id in reservations.values() and reservations[bed_id] != p.id)
            ):
                violations.append("invalid_admission")
                continue
            unit = units[beds[bed_id].unit_id]
            occupied = sum(
                b.unit_id == unit.id and occupants[b.id] is not None for b in beds.values()
            )
            other_reservations = sum(
                b.unit_id == unit.id and reservations[b.id] not in (None, p.id)
                for b in beds.values()
            )
            if unit.staffed_beds is None or occupied + other_reservations >= unit.staffed_beds:
                violations.append("staffed_capacity")
            waiting.remove(p.id)
            occupants[bed_id] = p.id
            reservations[bed_id] = None
            status[bed_id] = "occupied"
            admitted += 1
        else:
            violations.append("unknown_event")
        present = [p for p in occupants.values() if p is not None]
        if (
            len(set(present)) != len(present)
            or waiting & departed
            or set(present) & (waiting | departed)
            or waiting | set(present) | departed != patients.keys()
        ):
            violations.append("patient_conservation")
    area += len(waiting) * (trajectory.horizon_minutes - clock)
    integrate_pressure(trajectory.horizon_minutes - clock)
    if seen != expected.keys():
        violations.append("missing_external_event")
    return Score(
        area,
        admitted,
        len(waiting),
        tuple(violations),
        arrived,
        cancelled,
        ResourcePressure(*exposure),
    )
