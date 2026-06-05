"""Canonical Pydantic v2 schemas for SIH events."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class CanonicalBase(BaseModel):
    """Shared canonical event metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: UUID = Field(default_factory=uuid4)
    hospital_id: str
    service_id: str
    source_system: str
    received_at: datetime


class CanonicalAdmission(CanonicalBase):
    """Canonical admission event."""

    patient_id: str
    encounter_id: str
    admission_time: datetime
    admission_type: str


class CanonicalDischarge(CanonicalBase):
    """Canonical discharge event."""

    patient_id: str
    encounter_id: str
    discharge_time: datetime
    discharge_disposition: str


class CanonicalCareLoad(CanonicalBase):
    """Canonical care load measurement."""

    measured_at: datetime
    siips_score: float
    aas_score: float | None = None
    patient_count: int


class CanonicalStaffing(CanonicalBase):
    """Canonical staffing event."""

    shift_start: datetime
    shift_end: datetime
    nurse_count: float
    aide_count: float
    overtime_hours: float = 0.0
    avg_seniority_months: float | None = None
