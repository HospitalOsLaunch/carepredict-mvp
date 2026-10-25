"""Declared JSON export -> existing SourceAdapter -> existing shadow LiveStore."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from hospitalos.hybrid.live_models import LivePolicy
from hospitalos.hybrid.live_store import LiveStore
from hospitalos.hybrid.models import Bed, Discharge, Fact, FactEvent, Patient, Unit
from hospitalos.hybrid.source_adapter import SourceAdapter
from hospitalos.hybrid.source_contract import KINDS, SourceProfile, TableMapping, expected_fields

from .engine import HOSPITAL, SOURCE, START, UNIT, Frame


class DeclaredFeed:
    def __init__(self, clock: Callable[[], datetime]) -> None:
        self.store = LiveStore(LivePolicy(hospital_id=HOSPITAL, unit_id=UNIT, sources=(SOURCE,)))
        tables = tuple(
            TableMapping(
                kind=k,
                table=f"sim_{k}",
                columns={f: f.replace(".", "_") for f in sorted(expected_fields(k))},
            )
            for k in KINDS
        )
        self.profile = SourceProfile(
            profile_id="geriatric-demo",
            version=1,
            source_schema="DEMO_DECLARED_1",
            hospital_id=HOSPITAL,
            unit_id=UNIT,
            source=SOURCE,
            upstream_pseudonymized_ids=True,
            tables=tables,
        )
        self.adapter = SourceAdapter(self.store, self.profile, clock)
        self.sequence = 0
        self.manifest_version = 0
        self.expected: tuple[str, ...] = ()

    def receive(self, frame: Frame) -> None:
        self.sequence += 1
        facts: list[Fact] = [Unit(id=UNIT, staffed_beds=3, cleaning_teams=1)]
        for b in frame.beds:
            facts.append(
                Bed(
                    id=b.id,
                    unit_id=UNIT,
                    state="occupied"
                    if b.occupant
                    else "closed"
                    if not b.opened
                    else "clean"
                    if b.hygiene == "ready"
                    else "dirty",
                    capabilities=("oxygen",) if b.oxygen else (),
                    occupant=b.occupant,
                    reserved_for=b.reserved_for,
                )
            )
        for p in frame.patients:
            facts.append(
                Patient(
                    id=p.id,
                    status=p.status,
                    compatible_units=(UNIT,),
                    requirements=("oxygen",) if p.oxygen else (),
                    priority=2 if p.oxygen else 1,
                    waiting_since=START + timedelta(seconds=p.since),
                    bed_id=p.bed,
                    medically_cleared=p.cleared if p.status == "admitted" else None,
                    downstream_confirmed=True if p.cleared else None,
                )
            )
            if p.status == "admitted":
                facts.append(
                    Discharge(
                        id=p.id,
                        documents_ready=p.cleared,
                        escort_required=False,
                        downstream_required=False,
                        transport_required=False,
                    )
                )
        expected = tuple(sorted(f"{f.kind}:{f.id}" for f in facts))
        if expected != self.expected:
            self.manifest_version += 1
            self.expected = expected
        rows: dict[str, list[dict[str, Any]]] = {t.table: [] for t in self.profile.tables}
        for fact in facts:
            event = FactEvent(
                hospital_id=HOSPITAL,
                event_id=f"observation:{self.sequence}:{fact.kind}:{fact.id}",
                source=SOURCE,
                event_time=frame.observed_at,
                available_at=frame.observed_at,
                fact=fact,
            ).model_dump(mode="json")
            table = next(t for t in self.profile.tables if t.kind == fact.kind)
            rows[table.table].append(
                {
                    source: event["fact"][target.removeprefix("fact.")]
                    if target.startswith("fact.")
                    else event[target]
                    for target, source in table.columns.items()
                }
            )
        availability = next(t for t in self.profile.tables if t.kind == "availability")
        committed = sum(b.occupant is not None or b.reserved_for is not None for b in frame.beds)
        for resource, count in (("staffed", 3 - committed), ("cleaning", frame.cleaning_available)):
            values: dict[str, Any] = {
                "resource": resource,
                "target_id": UNIT,
                "available": count,
                "observed_at": frame.observed_at.isoformat(),
                "evidence_ref": f"direct-observation:{self.sequence}:{resource}",
            }
            rows[availability.table].append({v: values[k] for k, v in availability.columns.items()})
        result = self.adapter.receive(
            json.dumps(
                {
                    "schema_version": "UNIT_SOURCE_EXPORT_1",
                    "source_schema": "DEMO_DECLARED_1",
                    "export_id": f"snapshot-{self.sequence}",
                    "hospital_id": HOSPITAL,
                    "unit_id": UNIT,
                    "source": SOURCE,
                    "exported_at": frame.observed_at.isoformat(),
                    "manifest_version": self.manifest_version,
                    "expected_entities": expected,
                    "tables": rows,
                }
            ).encode()
        )
        if result.report.status == "REJECTED":
            raise ValueError(f"simulator_export_rejected:{result.report.issues}")
