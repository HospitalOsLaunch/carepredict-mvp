"""Independent event-log scorer; does not call the transition generator."""

from __future__ import annotations

from dataclasses import dataclass

from .models import State, compatible
from .simulation import Trajectory


@dataclass(frozen=True)
class Score:
    waiting_patient_minutes: int
    admitted: int
    waiting_at_end: int
    violations: tuple[str, ...]


def score(state: State, trajectory: Trajectory) -> Score:
    beds = {b.id: b for b in state.beds}
    patients = {p.id: p for p in state.patients}
    units = {u.id: u for u in state.units}
    occupants = {b.id: b.occupant for b in state.beds}
    status: dict[str, str] = {b.id: b.state for b in state.beds}
    reservations = {b.id: b.reserved_for for b in state.beds}
    waiting = {p.id for p in state.patients if p.status == "waiting"}
    departed = {p.id for p in state.patients if p.status == "departed"}
    admitted, area, clock = 0, 0, 0
    violations: list[str] = []
    for event in trajectory.events:
        if not clock <= event.minute <= trajectory.horizon_minutes:
            violations.append("event_time")
            continue
        area += len(waiting) * (event.minute - clock)
        clock = event.minute
        if event.bed_id not in beds:
            violations.append("unknown_bed")
            continue
        bed_id = event.bed_id
        if event.kind == "reserve":
            p = patients.get(event.patient_id or "")
            if (
                p is None
                or p.id not in waiting
                or status[bed_id] != "clean"
                or reservations[bed_id] is not None
                or p.id in reservations.values()
                or not compatible(p, beds[bed_id])
            ):
                violations.append("invalid_reservation")
                continue
            unit = units[beds[bed_id].unit_id]
            committed = sum(
                b.unit_id == unit.id
                and (occupants[b.id] is not None or reservations[b.id] is not None)
                for b in beds.values()
            )
            if unit.staffed_beds is None or committed >= unit.staffed_beds:
                violations.append("reservation_capacity")
            reservations[bed_id] = p.id
        elif event.kind == "depart":
            p = patients.get(event.patient_id or "")
            if (
                p is None
                or occupants[bed_id] != p.id
                or p.medically_cleared is not True
                or p.downstream_confirmed is not True
            ):
                violations.append("invalid_departure")
                continue
            departed.add(p.id)
            occupants[bed_id] = None
            status[bed_id] = "dirty"
        elif event.kind == "clean_start":
            if status[bed_id] != "dirty":
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
            if unit.staffed_beds is None or occupied >= unit.staffed_beds:
                violations.append("staffed_capacity")
            waiting.remove(p.id)
            occupants[bed_id] = p.id
            reservations[bed_id] = None
            status[bed_id] = "occupied"
            admitted += 1
        else:
            violations.append("unknown_event")
        present = [p for p in occupants.values() if p is not None]
        if len(set(present)) != len(present) or len(waiting) + len(present) + len(departed) != len(
            patients
        ):
            violations.append("patient_conservation")
    area += len(waiting) * (trajectory.horizon_minutes - clock)
    return Score(area, admitted, len(waiting), tuple(violations))
