"""Versioned, source-independent patient/resource facts for the hybrid MVP.

This patient-level extension is not inferred from aggregate OPERATIONAL_V2 data.
Identifiers must be pseudonymous; the contract itself does not anonymize data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator

from hospitalos.operational.contract import Closed, Identifier, instant

Count = Annotated[StrictInt, Field(ge=0)]


class Unit(Closed):
    kind: Literal["unit"] = "unit"
    id: Identifier
    staffed_beds: Count | None
    cleaning_teams: Count | None


class Bed(Closed):
    kind: Literal["bed"] = "bed"
    id: Identifier
    unit_id: Identifier
    state: Literal["clean", "dirty", "occupied", "closed", "unknown"]
    capabilities: tuple[Identifier, ...] = ()
    occupant: Identifier | None = None
    reserved_for: Identifier | None = None

    @model_validator(mode="after")
    def occupancy(self) -> Self:
        if (self.state == "occupied") != (self.occupant is not None):
            raise ValueError("Occupied beds require exactly one occupant")
        if self.reserved_for is not None and self.state != "clean":
            raise ValueError("This version only supports reservations on clean beds")
        return self


class Patient(Closed):
    kind: Literal["patient"] = "patient"
    id: Identifier
    status: Literal["waiting", "admitted", "departed"]
    compatible_units: tuple[Identifier, ...]
    requirements: tuple[Identifier, ...] = ()
    # Priority is supplied by an authorized professional, never inferred here.
    priority: Annotated[StrictInt, Field(ge=1, le=5)] = 1
    waiting_since: datetime
    bed_id: Identifier | None = None
    medically_cleared: StrictBool | None = None
    downstream_confirmed: StrictBool | None = None

    @field_validator("waiting_since")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return instant(value)

    @model_validator(mode="after")
    def location(self) -> Self:
        if (self.status == "admitted") != (self.bed_id is not None):
            raise ValueError("Admitted patients require a bed; others must have no bed")
        return self


class ResourcePool(Closed):
    """Residual resources available at D, excluding commitments outside this cohort."""

    kind: Literal["pool"] = "pool"
    id: Identifier
    resource: Literal["transport", "downstream"]
    unit_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    available: Count | None


class Discharge(Closed):
    """Professional attestations, not a clinical discharge checklist or prediction.

    id is the patient identifier. Required=False explicitly means not applicable;
    None is unknown. No legacy boolean is expanded into logistics confirmations.
    """

    kind: Literal["discharge"] = "discharge"
    id: Identifier
    documents_ready: StrictBool | None = None
    escort_required: StrictBool | None = None
    escort_confirmed: StrictBool | None = None
    downstream_required: StrictBool | None = None
    downstream_pool_id: Identifier | None = None
    transport_required: StrictBool | None = None
    transport_pool_id: Identifier | None = None
    transport_requested: StrictBool | None = None

    @model_validator(mode="after")
    def applicability(self) -> Self:
        for name in ("transport", "downstream"):
            if getattr(self, f"{name}_required") is not True and getattr(self, f"{name}_pool_id"):
                raise ValueError("A pool reference requires an explicitly required resource")
        if self.transport_requested is True and self.transport_required is not True:
            raise ValueError("A transport request requires an explicitly required transport")
        return self


Fact = Annotated[Unit | Bed | Patient | ResourcePool | Discharge, Field(discriminator="kind")]


class FactEvent(Closed):
    schema_version: Literal["HYBRID_MVP_2"] = "HYBRID_MVP_2"
    hospital_id: Identifier
    event_id: Identifier
    version: Annotated[StrictInt, Field(ge=1)] = 1
    source: Identifier
    event_time: datetime
    available_at: datetime
    fact: Fact

    @field_validator("event_time", "available_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return instant(value)

    @model_validator(mode="after")
    def clocks(self) -> Self:
        if self.available_at < self.event_time:
            raise ValueError("A fact cannot be available before its event time")
        if isinstance(self.fact, Patient) and self.fact.waiting_since > self.event_time:
            raise ValueError("Patient history cannot start after the observed fact")
        return self


class State(Closed):
    hospital_id: Identifier
    at: datetime
    fingerprint: str
    units: tuple[Unit, ...]
    beds: tuple[Bed, ...]
    patients: tuple[Patient, ...]
    pools: tuple[ResourcePool, ...] = ()
    discharges: tuple[Discharge, ...] = ()
    issues: tuple[str, ...] = ()
    # Observed overload is retained and exposed, not clamped to capacity.
    warnings: tuple[str, ...] = ()


class Action(Closed):
    kind: Literal["no_op", "prioritize_cleaning", "reserve_bed", "request_transport"]
    bed_id: Identifier | None = None
    patient_id: Identifier | None = None

    @model_validator(mode="after")
    def arguments(self) -> Self:
        if self.kind == "no_op" and (self.bed_id or self.patient_id):
            raise ValueError("no_op has no arguments")
        if self.kind == "prioritize_cleaning" and (not self.bed_id or self.patient_id):
            raise ValueError("Cleaning requires only a bed")
        if self.kind in {"reserve_bed", "request_transport"} and (
            not self.bed_id or not self.patient_id
        ):
            raise ValueError("This action requires a patient and bed")
        return self

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.bed_id or ''}:{self.patient_id or ''}"


def compatible(patient: Patient, bed: Bed) -> bool:
    return bed.unit_id in patient.compatible_units and set(patient.requirements) <= set(
        bed.capabilities
    )


def discharge_blockers(
    state: State, patient: Patient, *, include_request: bool = True, require_capacity: bool = True
) -> tuple[str, ...]:
    """Snapshot prerequisites only; future resource contention is simulated separately."""
    reasons: list[str] = []
    if patient.status != "admitted":
        return ("patient_not_admitted",)
    if patient.medically_cleared is not True:
        reasons.append("medical_authorization_not_confirmed")
    d = next((d for d in state.discharges if d.id == patient.id), None)
    if d is None:
        return (*reasons, "discharge_logistics_missing")
    if d.documents_ready is not True:
        reasons.append("documents_not_confirmed")
    if d.escort_required is None or (d.escort_required and d.escort_confirmed is not True):
        reasons.append("escort_not_confirmed")
    bed = next((b for b in state.beds if b.id == patient.bed_id), None)
    for kind, required, pool_id in (
        ("downstream", d.downstream_required, d.downstream_pool_id),
        ("transport", d.transport_required, d.transport_pool_id),
    ):
        if required is None:
            reasons.append(f"{kind}_requirement_unknown")
        elif required:
            pool = next((r for r in state.pools if r.id == pool_id), None)
            if (
                pool is None
                or pool.resource != kind
                or bed is None
                or bed.unit_id not in pool.unit_ids
            ):
                reasons.append(f"{kind}_pool_unverified")
            elif pool.available is None or (require_capacity and pool.available == 0):
                reasons.append(f"{kind}_unavailable")
    if d.downstream_required and patient.downstream_confirmed is not True:
        reasons.append("downstream_acceptance_not_confirmed")
    if include_request and d.transport_required and d.transport_requested is not True:
        reasons.append("transport_not_requested")
    return tuple(reasons)


def action_errors(state: State, action: Action) -> tuple[str, ...]:
    """Reused by candidate construction AND just-in-time dispatch validation."""
    if state.issues:
        return state.issues
    if action.kind == "no_op":
        return ()
    beds = {b.id: b for b in state.beds}
    bed = beds.get(action.bed_id or "")
    if bed is None:
        return ("bed_missing",)
    unit = next((u for u in state.units if u.id == bed.unit_id), None)
    if unit is None:
        return ("unit_missing",)
    if action.kind == "prioritize_cleaning":
        return () if bed.state == "dirty" and unit.cleaning_teams else ("cleaning_unavailable",)
    patient = next((p for p in state.patients if p.id == action.patient_id), None)
    if action.kind == "request_transport":
        if patient is None or bed.occupant != patient.id or patient.bed_id != bed.id:
            return ("patient_location_mismatch",)
        d = next((d for d in state.discharges if d.id == patient.id), None)
        if d is None or d.transport_required is not True or d.transport_requested is not False:
            return ("transport_request_not_available",)
        return discharge_blockers(state, patient, include_request=False)
    if patient is None or patient.status != "waiting" or not compatible(patient, bed):
        return ("patient_incompatible_or_unavailable",)
    if bed.state != "clean" or bed.reserved_for is not None:
        return ("bed_unavailable",)
    if any(b.reserved_for == patient.id for b in state.beds):
        return ("patient_already_reserved",)
    committed = sum(
        b.unit_id == unit.id and (b.state == "occupied" or b.reserved_for is not None)
        for b in state.beds
    )
    if unit.staffed_beds is None or committed >= unit.staffed_beds:
        return ("staffed_capacity_unavailable",)
    return ()
