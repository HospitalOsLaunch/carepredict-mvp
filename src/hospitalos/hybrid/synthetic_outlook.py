"""Deterministic synthetic source exports. No observations or labels are read from after D."""

from datetime import timedelta

from hospitalos.decision_support.contracts import StaffShift

from .models import State
from .outlook import (
    Bookings,
    DayDemand,
    DepartureEstimate,
    Departures,
    Emergency,
    Roster,
    StaffCapacity,
    UnitOutlook,
    civil_days,
)


def synthetic_outlook(state: State, unit: str, days: int = 7) -> UnitOutlook:
    at, end = state.at, state.at + timedelta(days=days)
    common = {
        "hospital_id": state.hospital_id,
        "unit_id": unit,
        "revision": 1,
        "provenance": "synthetic",
        "issued_at": at,
        "available_at": at,
        "synced_at": at,
        "covers_from": at,
        "covers_until": end,
        "status": "complete",
    }
    schedules = [s for s in state.schedules if s.id == unit]
    bookings = Bookings.model_validate(
        {
            **common,
            "source": "syn-bookings",
            "records": [b for s in schedules for b in s.admissions],
        }
    )
    occupied = sorted(b.occupant for b in state.beds if b.unit_id == unit and b.occupant)
    departures = Departures.model_validate(
        {
            **common,
            "source": "syn-departures",
            "records": [
                DepartureEstimate(
                    stay_id=pid, reviewed_at=at, estimate=at + timedelta(days=1 + i % days)
                )
                for i, pid in enumerate(occupied)
            ],
        }
    )
    capacity = next((u.staffed_beds or 0 for u in state.units if u.id == unit), 0)
    shifts = []
    bands = []
    for block in range(2 * days):
        start = at + timedelta(hours=12 * block)
        stop = start + timedelta(hours=12)
        bands.append(
            StaffCapacity(
                start=start, end=stop, staffed_beds=capacity, required={"IDE": 1, "AS": 1}
            )
        )
        for skill in ("IDE", "AS"):
            shifts.append(
                StaffShift.model_validate(
                    {
                        "staff_id": f"{unit}-{skill}-{block % 4}",
                        "skill": skill,
                        "start": start,
                        "end": stop,
                        "status": "confirmed",
                    }
                )
            )
    roster = Roster.model_validate(
        {
            **common,
            "source": "syn-roster",
            "validated": True,
            "shifts": shifts,
            "external_shifts": (),
            "capacity": bands,
        }
    )
    emergency = Emergency.model_validate(
        {
            **common,
            "source": "syn-ed",
            "allocation_rule": "direct-to-beneficiary-v1",
            "records": [
                DayDemand(day=day, counts=(0, 1, 2) if day.weekday() < 5 else (0, 1))
                for day in civil_days(at, end, "Europe/Paris")
            ],
        }
    )
    return UnitOutlook(id=unit, feeds=(bookings, departures, roster, emergency))
