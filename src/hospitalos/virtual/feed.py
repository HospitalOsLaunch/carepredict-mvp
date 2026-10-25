"""Declared JSON export -> existing SourceAdapter -> existing shadow LiveStore."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from hospitalos.hybrid.live_models import LivePolicy
from hospitalos.hybrid.live_store import LiveStore
from hospitalos.hybrid.models import Bed, Discharge, Fact, FactEvent, Patient, ResourcePool, Unit
from hospitalos.hybrid.source_adapter import SourceAdapter
from hospitalos.hybrid.source_contract import KINDS, SourceProfile, TableMapping, expected_fields
from hospitalos.simulator.engine import START, Frame

from .clinical import CareBed, CareFrame, CarePatient
from .config import HospitalConfig


class VirtualFeed:
    def __init__(
        self, clock: Callable[[], datetime], config: HospitalConfig, *, epoch: datetime = START
    ) -> None:
        self.clock, self.config = clock, config
        self.epoch = epoch
        self.source = f"virtual-si-{config.hospital_id}" + (
            f"-{config.unit_id}" if epoch != START else ""
        )
        self.store = LiveStore(
            LivePolicy(
                hospital_id=self.config.hospital_id,
                unit_id=self.config.unit_id,
                sources=(self.source,),
            )
        )
        tables = tuple(
            TableMapping(
                kind=k,
                table=f"sim_{k}",
                columns={f: f.replace(".", "_") for f in sorted(expected_fields(k))},
            )
            for k in KINDS
        )
        self.profile = SourceProfile(
            profile_id=f"virtual-{config.hospital_id}",
            version=1,
            source_schema="DEMO_DECLARED_1",
            hospital_id=self.config.hospital_id,
            unit_id=self.config.unit_id,
            source=self.source,
            upstream_pseudonymized_ids=True,
            tables=tables,
        )
        self.adapter = SourceAdapter(self.store, self.profile, clock)
        self.sequence = 0
        self.manifest_version = 0
        self.expected: tuple[str, ...] = ()

    def receive(self, frame: Frame) -> None:
        # This adapter consumes complete, receipt-stamped exports. Its projection is bounded;
        # frozen decision evidence and the replayable command ledger live in HospitalRuntime.
        self.store.close()
        self.store = LiveStore(
            LivePolicy(
                hospital_id=self.config.hospital_id,
                unit_id=self.config.unit_id,
                sources=(self.source,),
            )
        )
        self.adapter = SourceAdapter(self.store, self.profile, self.clock)
        self.manifest_version = 0
        self.expected = ()
        self.sequence += 1
        facts: list[Fact] = [
            Unit(
                id=self.config.unit_id,
                staffed_beds=frame.staffed_beds
                if isinstance(frame, CareFrame)
                else self.config.staffed_beds,
                cleaning_teams=self.config.cleaning_teams,
            )
        ]
        for b in frame.beds:
            facts.append(
                Bed(
                    id=b.id,
                    unit_id=self.config.unit_id,
                    state="occupied"
                    if b.occupant
                    else "closed"
                    if not b.opened
                    or (
                        isinstance(frame, CareFrame)
                        and b.id in frame.held_beds
                        and not b.reserved_for
                    )
                    else "clean"
                    if b.hygiene == "ready"
                    else "dirty",
                    capabilities=(("oxygen",) if b.oxygen else ())
                    + (("isolation",) if isinstance(b, CareBed) and b.isolation else ()),
                    occupant=b.occupant,
                    reserved_for=b.reserved_for,
                )
            )
        for p in frame.patients:
            facts.append(
                Patient(
                    id=p.id,
                    status=p.status,
                    compatible_units=p.compatible_units
                    if isinstance(p, CarePatient)
                    else (self.config.unit_id,),
                    requirements=(("oxygen",) if p.oxygen else ())
                    + (("isolation",) if isinstance(p, CarePatient) and p.isolation else ()),
                    priority=2 if p.oxygen else 1,
                    waiting_since=self.epoch + timedelta(seconds=p.since),
                    bed_id=p.bed,
                    medically_cleared=p.cleared
                    if p.status == "admitted"
                    and (not isinstance(p, CarePatient) or p.discharge_planned)
                    else None,
                    downstream_confirmed=p.downstream_ready
                    if isinstance(p, CarePatient) and p.downstream_required
                    else True
                    if p.cleared
                    else None,
                )
            )
            if p.status == "admitted" and (not isinstance(p, CarePatient) or p.discharge_planned):
                facts.append(
                    Discharge(
                        id=p.id,
                        documents_ready=p.documents_ready
                        if isinstance(p, CarePatient)
                        else p.cleared,
                        escort_required=False,
                        downstream_required=p.downstream_required
                        if isinstance(p, CarePatient)
                        else False,
                        downstream_pool_id=f"{p.id}-downstream"
                        if isinstance(p, CarePatient) and p.downstream_required
                        else None,
                        transport_required=p.transport_required
                        if isinstance(p, CarePatient)
                        else False,
                        transport_pool_id=f"{p.id}-transport"
                        if isinstance(p, CarePatient) and p.transport_required
                        else None,
                        transport_requested=p.transport_requested
                        if isinstance(p, CarePatient) and p.transport_required
                        else None,
                    )
                )
        if isinstance(frame, CareFrame):
            # Confirmed logistics belong to the named patient, not to every discharge
            # in the unit. A separate synthetic pool prevents cross-patient readiness.
            for p in frame.patients:
                if (
                    not isinstance(p, CarePatient)
                    or p.status != "admitted"
                    or not p.discharge_planned
                ):
                    continue
                for resource in ("transport", "downstream"):
                    if getattr(p, f"{resource}_required"):
                        facts.append(
                            ResourcePool(
                                id=f"{p.id}-{resource}",
                                resource=resource,
                                unit_ids=(self.config.unit_id,),
                                available=int(getattr(p, f"{resource}_ready")),
                            )
                        )
        expected = tuple(sorted(f"{f.kind}:{f.id}" for f in facts))
        if expected != self.expected:
            self.manifest_version += 1
            self.expected = expected
        rows: dict[str, list[dict[str, Any]]] = {t.table: [] for t in self.profile.tables}
        for fact in facts:
            event = FactEvent(
                hospital_id=self.config.hospital_id,
                event_id=f"observation:{self.sequence}:{fact.kind}:{fact.id}",
                source=self.source,
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
        for resource, count in (
            (
                "staffed",
                max(
                    0,
                    (
                        frame.staffed_beds
                        if isinstance(frame, CareFrame)
                        else self.config.staffed_beds
                    )
                    - committed,
                ),
            ),
            ("cleaning", frame.cleaning_available),
        ):
            values: dict[str, Any] = {
                "resource": resource,
                "target_id": self.config.unit_id,
                "available": count,
                "observed_at": frame.observed_at.isoformat(),
                "evidence_ref": f"direct-observation:{self.sequence}:{resource}",
            }
            rows[availability.table].append({v: values[k] for k, v in availability.columns.items()})
        for fact in facts:
            if isinstance(fact, ResourcePool):
                values = {
                    "resource": fact.resource,
                    "target_id": fact.id,
                    "available": fact.available,
                    "observed_at": frame.observed_at.isoformat(),
                    "evidence_ref": f"direct-observation:{self.sequence}:{fact.id}",
                }
                rows[availability.table].append(
                    {v: values[k] for k, v in availability.columns.items()}
                )
        result = self.adapter.receive(
            json.dumps(
                {
                    "schema_version": "UNIT_SOURCE_EXPORT_1",
                    "source_schema": "DEMO_DECLARED_1",
                    "export_id": f"snapshot-{self.sequence}",
                    "hospital_id": self.config.hospital_id,
                    "unit_id": self.config.unit_id,
                    "source": self.source,
                    "exported_at": frame.observed_at.isoformat(),
                    "manifest_version": self.manifest_version,
                    "expected_entities": expected,
                    "tables": rows,
                }
            ).encode()
        )
        if result.report.status == "REJECTED":
            raise ValueError(f"simulator_export_rejected:{result.report.issues}")
