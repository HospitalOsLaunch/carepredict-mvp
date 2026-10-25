"""Post-episode reconstruction, independent of the planner's utility and engine counters."""

from __future__ import annotations

from collections.abc import Sequence

from hospitalos.operational.contract import Closed

from .engine import TruthEvent


class Evaluation(Closed):
    waiting_patient_minutes: float
    waiting_at_end: int
    admitted_at_end: int
    departed: int
    patients_total: int
    completed_cleanings: int
    coordination_tasks: int
    scope: str = "fictional_scenario_only_no_effectiveness_claim"


def evaluate(events: Sequence[TruthEvent], until: float) -> Evaluation:
    patients: dict[str, str] = {}
    occupants: dict[str, str] = {}
    last = area = 0.0
    cleanings = tasks = 0
    for e in events:
        if not last <= e.second <= until:
            raise ValueError("invalid_event_time")
        area += (e.second - last) * sum(s == "waiting" for s in patients.values())
        last = e.second
        if e.kind in {"initial_waiting", "initial_admitted", "arrived"}:
            if e.patient is None or e.patient in patients:
                raise ValueError("duplicate_or_missing_patient")
            patients[e.patient] = "admitted" if e.kind == "initial_admitted" else "waiting"
            if e.kind == "initial_admitted":
                if e.bed is None or e.bed in occupants:
                    raise ValueError("duplicate_bed")
                occupants[e.bed] = e.patient
        elif e.kind == "installed":
            if e.patient is None or patients.get(e.patient) != "waiting" or e.bed is None:
                raise ValueError("invalid_installation")
            if e.bed in occupants:
                raise ValueError("double_occupancy")
            occupants[e.bed] = e.patient
            patients[e.patient] = "admitted"
        elif e.kind == "departed":
            if (
                e.patient is None
                or patients.get(e.patient) != "admitted"
                or e.bed is None
                or occupants.get(e.bed) != e.patient
            ):
                raise ValueError("invalid_departure")
            del occupants[e.bed]
            patients[e.patient] = "departed"
        elif e.kind == "cleaning_finished":
            cleanings += 1
        elif e.kind == "coordination_requested":
            tasks += 1
    area += (until - last) * sum(s == "waiting" for s in patients.values())
    return Evaluation(
        waiting_patient_minutes=area / 60,
        waiting_at_end=sum(s == "waiting" for s in patients.values()),
        admitted_at_end=sum(s == "admitted" for s in patients.values()),
        departed=sum(s == "departed" for s in patients.values()),
        patients_total=len(patients),
        completed_cleanings=cleanings,
        coordination_tasks=tasks,
    )
