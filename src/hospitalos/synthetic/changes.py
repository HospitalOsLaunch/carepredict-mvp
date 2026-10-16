"""Dated exogenous organisation changes; schedules are truth, never policy inputs."""

from __future__ import annotations

import datetime as dt
from typing import Any

import numpy as np

from .config import BedClosure, HospitalConfig, OrganisationalChange, ServiceCapacityChange
from .mechanisms import RESOURCE_ARRAYS


def bounds(config: HospitalConfig, change: OrganisationalChange) -> tuple[int, int]:
    start = dt.datetime.combine(config.start, dt.time(), dt.timezone(dt.timedelta(hours=1)))
    first = int((change.starts_at - start).total_seconds() // 3600)
    last = (
        int((change.ends_at - start).total_seconds() // 3600)
        if change.ends_at
        else config.days * 24
    )
    return first, last


def apply_changes(exo: Any, config: HospitalConfig) -> None:
    """Called once after reference draws/scaling, before resource-pool allocation.

    No random numbers consumed and no patient/calendar/policy arrays touched.
    Windows of the same kind/target cannot overlap, so effects are order independent.
    """
    if getattr(exo, "organisation_changes_applied", False):
        raise ValueError("Organisation changes already applied to this exogenous state")
    if not config.changes:
        return
    indices = {u.unit_id: i for i, u in enumerate(config.units)}
    offset = config.warmup_days * 24
    for change in config.changes:
        begin, end = bounds(config, change)
        begin, end = begin + offset, end + offset
        if isinstance(change, BedClosure):
            unit = indices[change.unit_id]
            exo.fermes[unit, begin:end] = np.minimum(
                exo.fermes[unit, begin:end] + change.additional_closed_beds, exo.nb_std[unit]
            )
        elif isinstance(change, ServiceCapacityChange):
            capacity = getattr(exo, RESOURCE_ARRAYS[change.resource])
            capacity[begin:end] = np.floor(capacity[begin:end] * change.multiplier).astype(int)
        else:
            unit = indices[change.unit_id]
            slots = sorted({exo.sid(hour) for hour in range(begin, end)})
            exo.absents[unit, slots] = np.minimum(
                exo.absents[unit, slots] + change.additional_absent, exo.prevus[unit, slots]
            )
    exo.organisation_changes_applied = True


def boundary_events(config: HospitalConfig) -> dict[int, list[dict[str, Any]]]:
    """Start/end audit records only. No future boundary is emitted in a past step."""
    events: dict[int, list[dict[str, Any]]] = {}
    for change in sorted(config.changes, key=lambda c: (c.starts_at, c.change_id)):
        start, end = bounds(config, change)
        if isinstance(change, ServiceCapacityChange):
            target: str = change.resource
            scope = "hospital"
            value: int | float = change.multiplier
        else:
            target, scope = change.unit_id, "unit"
            value = (
                change.additional_closed_beds
                if isinstance(change, BedClosure)
                else change.additional_absent
            )
        for hour, boundary in ((start, "start"), (end, "end")):
            if hour >= config.days * 24:
                continue
            events.setdefault(hour, []).append(
                {
                    "change_id": change.change_id,
                    "kind": change.kind,
                    "scope": scope,
                    "target": target,
                    "boundary": boundary,
                    "requested_value": value,
                    "semantics": "apply_relative_to_reference"
                    if boundary == "start"
                    else "restore_reference",
                }
            )
    for records in events.values():
        records.sort(key=lambda r: (r["boundary"] != "end", r["change_id"]))
    return events


def log_boundaries(sim: Any, journal: Any, hour: int) -> None:
    for record in getattr(sim, "organisation_boundaries", {}).get(hour - sim.h0_rec, ()):
        unit = sim.x.unit_names.index(record["target"]) if record["scope"] == "unit" else 0
        journal.event(hour, "ORGANISATION_CHANGE", unit, None, **record)
