"""Append-only SQLite fact journal and conservative bitemporal reconstruction."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime

from hospitalos.operational.contract import instant

from .models import Bed, Discharge, FactEvent, Patient, ResourcePool, State, Unit, compatible


def canonical(event: FactEvent) -> str:
    return json.dumps(event.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


class Journal:
    """Local prototype persistence. A production deployment needs access controls/backups."""

    def __init__(self, path: str = ":memory:") -> None:
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS facts (hospital TEXT, event TEXT, version INTEGER, "
            "body TEXT NOT NULL, PRIMARY KEY (hospital, event, version))"
        )

    def append(self, event: FactEvent) -> bool:
        with self.db:
            rows = self.db.execute(
                "SELECT body FROM facts WHERE hospital=? AND event=?",
                (event.hospital_id, event.event_id),
            ).fetchall()
            for (body,) in rows:
                previous = FactEvent.model_validate_json(body)
                old_identity = (
                    previous.source,
                    previous.event_time,
                    previous.fact.kind,
                    previous.fact.id,
                )
                identity = (event.source, event.event_time, event.fact.kind, event.fact.id)
                if old_identity != identity:
                    raise ValueError("An event correction cannot change its identity")
                if previous.version == event.version:
                    if canonical(previous) != canonical(event):
                        raise ValueError("Conflicting event version")
                    return False
            self.db.execute(
                "INSERT INTO facts VALUES (?, ?, ?, ?)",
                (event.hospital_id, event.event_id, event.version, canonical(event)),
            )
        return True

    def read(self, hospital_id: str) -> tuple[FactEvent, ...]:
        return tuple(
            FactEvent.model_validate_json(row[0])
            for row in self.db.execute("SELECT body FROM facts WHERE hospital=?", (hospital_id,))
        )

    def close(self) -> None:
        self.db.close()


def reconstruct(
    events: Iterable[FactEvent],
    hospital_id: str,
    at: datetime,
    expected_entities: tuple[str, ...],
    max_age_minutes: int = 60,
) -> State:
    """No simulator truth, forward fill of missing resources, or future corrections."""
    at = instant(at)
    if max_age_minutes <= 0:
        raise ValueError("Freshness threshold must be positive")
    visible: dict[tuple[str, int], FactEvent] = {}
    identities: dict[str, tuple[str, datetime, str, str]] = {}
    for event in events:
        if event.hospital_id != hospital_id or event.available_at > at or event.event_time > at:
            continue
        identity = (event.source, event.event_time, event.fact.kind, event.fact.id)
        if identities.setdefault(event.event_id, identity) != identity:
            raise ValueError("Event identity changed")
        key = (event.event_id, event.version)
        if key in visible and canonical(visible[key]) != canonical(event):
            raise ValueError("Conflicting event version")
        visible[key] = event
    revisions: dict[str, FactEvent] = {}
    for event in visible.values():
        old = revisions.get(event.event_id)
        if old is None or event.version > old.version:
            revisions[event.event_id] = event
    sources: dict[tuple[str, str, str], list[FactEvent]] = defaultdict(list)
    for event in revisions.values():
        sources[(event.fact.kind, event.fact.id, event.source)].append(event)
    entities: dict[tuple[str, str], list[FactEvent]] = defaultdict(list)
    for (kind, entity, _source), history in sources.items():
        latest_time = max(e.event_time for e in history)
        entities[(kind, entity)].extend(e for e in history if e.event_time == latest_time)
    issues: list[str] = []
    if not expected_entities or len(set(expected_entities)) != len(expected_entities):
        raise ValueError("An explicit unique perimeter manifest is required")
    observed_entities = {f"{kind}:{entity}" for kind, entity in entities}
    issues.extend(f"missing:{key}" for key in set(expected_entities) - observed_entities)
    issues.extend(f"undeclared:{key}" for key in observed_entities - set(expected_entities))
    selected: list[FactEvent] = []
    for (kind, entity), reports in sorted(entities.items()):
        contents = {e.fact.model_dump_json() for e in reports}
        if len(contents) != 1:
            issues.append(f"conflicting_sources:{kind}:{entity}")
            continue
        # Agreement is usable only if each contributing report is fresh.
        if any((at - e.event_time).total_seconds() > max_age_minutes * 60 for e in reports):
            issues.append(f"stale:{kind}:{entity}")
            continue
        selected.append(sorted(reports, key=lambda e: (e.event_id, e.version))[0])
    units = tuple(e.fact for e in selected if isinstance(e.fact, Unit))
    beds = tuple(e.fact for e in selected if isinstance(e.fact, Bed))
    patients = tuple(e.fact for e in selected if isinstance(e.fact, Patient))
    pools = tuple(e.fact for e in selected if isinstance(e.fact, ResourcePool))
    discharges = tuple(e.fact for e in selected if isinstance(e.fact, Discharge))
    unit_map, bed_map, patient_map = (
        {u.id: u for u in units},
        {b.id: b for b in beds},
        {p.id: p for p in patients},
    )
    warnings: list[str] = []
    pool_map = {pool.id: pool for pool in pools}
    for pool in pools:
        if pool.available is None:
            issues.append(f"unknown_pool_capacity:{pool.id}")
        if (
            len(set(pool.unit_ids)) != len(pool.unit_ids)
            or not set(pool.unit_ids) <= unit_map.keys()
        ):
            issues.append(f"invalid_pool_scope:{pool.id}")
    for discharge in discharges:
        patient = patient_map.get(discharge.id)
        if patient is None:
            issues.append(f"orphan_discharge:{discharge.id}")
            continue
        bed = bed_map.get(patient.bed_id or "")
        for kind, pool_id in (
            ("transport", discharge.transport_pool_id),
            ("downstream", discharge.downstream_pool_id),
        ):
            if pool_id is not None:
                linked_pool = pool_map.get(pool_id)
                if (
                    linked_pool is None
                    or linked_pool.resource != kind
                    or (bed is not None and bed.unit_id not in linked_pool.unit_ids)
                ):
                    issues.append(f"invalid_discharge_pool:{discharge.id}:{kind}")
    if not units or not beds:
        issues.append("missing_perimeter")
    reservations: set[str] = set()
    for unit in units:
        if unit.staffed_beds is None or unit.cleaning_teams is None:
            issues.append(f"unknown_resources:{unit.id}")
        occupied = sum(b.unit_id == unit.id and b.state == "occupied" for b in beds)
        if unit.staffed_beds is not None and occupied > unit.staffed_beds:
            warnings.append(f"observed_overload:{unit.id}")
    for bed in beds:
        if bed.unit_id not in unit_map or bed.state == "unknown":
            issues.append(f"unknown_bed_state_or_unit:{bed.id}")
        if bed.occupant is not None:
            patient = patient_map.get(bed.occupant)
            if patient is None or patient.status != "admitted" or patient.bed_id != bed.id:
                issues.append(f"occupancy_conflict:{bed.id}")
        if bed.reserved_for:
            patient = patient_map.get(bed.reserved_for)
            if (
                bed.reserved_for in reservations
                or patient is None
                or patient.status != "waiting"
                or not compatible(patient, bed)
            ):
                issues.append(f"reservation_conflict:{bed.id}")
            reservations.add(bed.reserved_for)
    for patient in patients:
        if patient.status == "admitted":
            assigned_bed = bed_map.get(patient.bed_id or "")
            if assigned_bed is None or assigned_bed.occupant != patient.id:
                issues.append(f"patient_location_conflict:{patient.id}")
    digest = hashlib.sha256(
        (
            hospital_id
            + "\n"
            + "\n".join(sorted(expected_entities))
            + "\n"
            + "\n".join(sorted(canonical(e) for e in visible.values()))
        ).encode()
    ).hexdigest()
    return State(
        hospital_id=hospital_id,
        at=at,
        fingerprint=digest,
        units=units,
        beds=beds,
        patients=patients,
        pools=pools,
        discharges=discharges,
        issues=tuple(sorted(set(issues))),
        warnings=tuple(sorted(warnings)),
    )
