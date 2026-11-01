"""HTTP contracts (Pydantic v2) of the LISCOP modules.

Each agent appends its own models under its own section only (see docs/liscop/PLAN.md),
so parallel branches merge without conflicts. Reuse ``Strict`` from ``schemas`` for inputs.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from services.admissions_smr.schemas import Strict

# --- beds-ed ---

BedAction = Literal["nettoye", "bloquer", "debloquer", "reserver", "annuler_reservation"]


class BedOut(BaseModel):
    id: int
    label: str
    room: str
    sex_constraint: str
    isolation: bool
    status: str
    status_reason: str | None
    occupant_sex: str | None
    accepts: list[str]  # sexes (F, M) the bed can take, given its room
    usable: bool
    updated_at: datetime


class BedActionIn(Strict):
    action: BedAction
    reason: str | None = Field(default=None, min_length=3, max_length=200)


class TensionOut(BaseModel):
    level: str
    availability_rate: float | None


class AvailabilityOut(BaseModel):
    installed: int
    occupied: int
    reserved: int
    cleaning: int
    blocked: int
    closed: int
    usable: int
    female: int
    male: int
    either: int
    isolation: int
    sex_conflict: int
    extra_beds: int
    crisis_reserved_beds: int
    tension: TensionOut


class RoomOut(BaseModel):
    room: str
    beds: list[BedOut]


class UnitBoardOut(BaseModel):
    pool_id: int
    code: str
    label: str
    unit_type: str
    discipline: str
    availability: AvailabilityOut
    rooms: list[RoomOut]


class SiteBoardOut(BaseModel):
    site_id: int
    site_name: str
    availability: AvailabilityOut
    units: list[UnitBoardOut]


class BedBoardOut(BaseModel):
    generated_at: datetime
    sites: list[SiteBoardOut]


class UnitAvailabilityOut(BaseModel):
    site_id: int
    site_name: str
    pool_id: int
    code: str
    label: str
    unit_type: str
    discipline: str
    ror_unit_id: str | None
    availability: AvailabilityOut


class SiteAvailabilityOut(BaseModel):
    site_id: int
    site_name: str
    availability: AvailabilityOut


class AvailabilityReportOut(BaseModel):
    generated_at: datetime
    units: list[UnitAvailabilityOut]
    sites: list[SiteAvailabilityOut]
    definitions: list[str]


class EdSiteOut(BaseModel):
    id: int
    name: str


class CensusNowOut(BaseModel):
    at: datetime
    present: int
    waiting_bed: int
    longest_wait_hours: float | None
    hosted_elsewhere: int


class Boarding10hOut(BaseModel):
    day: date
    at: datetime
    reached: bool  # False before 10:00: provisional count, read now with the same rule
    boarding: int
    computed_boarding: int
    source: str


class EdSnapshotOut(BaseModel):
    id: int
    site_id: int
    at: datetime
    present: int
    waiting_bed: int
    boarding: int
    hosted_elsewhere: int
    source: str
    comment: str | None


class EdCensusOut(BaseModel):
    site_id: int
    site_name: str
    ed_sites: list[EdSiteOut]
    now: CensusNowOut
    today_10h: Boarding10hOut
    latest_declaration: EdSnapshotOut | None
    definitions: list[str]


class BoardingDayOut(BaseModel):
    day: date
    present: int
    waiting_bed: int
    boarding: int
    hosted_elsewhere: int
    source: str
    computed_boarding: int


class BoardingSeriesOut(BaseModel):
    site_id: int
    days: list[BoardingDayOut]


class EdSnapshotIn(Strict):
    site_id: int
    at: datetime | None = None
    present: int = Field(ge=0, le=2000)
    waiting_bed: int = Field(ge=0, le=2000)
    boarding: int = Field(ge=0, le=2000)
    hosted_elsewhere: int = Field(default=0, ge=0, le=2000)
    comment: str | None = Field(default=None, max_length=1000)


class CriterionOut(BaseModel):
    code: str
    label: str
    value: float | None
    threshold: float
    triggered: bool


class HetAidOut(BaseModel):
    site_id: int
    level: str
    label: str
    criteria: list[CriterionOut]
    notice: str


class UnitTensionOut(BaseModel):
    site_id: int
    site_name: str
    pool_id: int
    code: str
    label: str
    discipline: str
    installed: int
    usable: int
    tension: TensionOut


class TensionDeclarationOut(BaseModel):
    id: int
    site_id: int | None
    kind: str
    level: str
    started_at: datetime
    ended_at: datetime | None
    declared_by: str
    comment: str | None


class TensionStatusOut(BaseModel):
    generated_at: datetime
    units: list[UnitTensionOut]
    aid: HetAidOut | None
    active_declarations: list[TensionDeclarationOut]


class TensionDeclarationIn(Strict):
    site_id: int | None = None
    kind: Literal["het", "plan_blanc"]
    level: str = Field(min_length=1, max_length=20)
    started_at: datetime | None = None
    comment: str | None = Field(default=None, max_length=2000)


class TensionDeclarationPatch(Strict):
    level: str | None = Field(default=None, min_length=1, max_length=20)
    ended_at: datetime | None = None
    comment: str | None = Field(default=None, max_length=2000)


# --- movement-ingest ---

# --- forecast-engine ---

# --- ror-oru-export ---
