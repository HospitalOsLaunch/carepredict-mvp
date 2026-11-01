"""HTTP contracts (Pydantic v2) of the LISCOP modules.

Each agent appends its own models under its own section only (see docs/liscop/PLAN.md),
so parallel branches merge without conflicts. Reuse ``Strict`` from ``schemas`` for inputs.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field

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

MOVEMENT_BATCH_MAX = 500  # items per POST /api/ingest/movements


class MovementIn(Strict):
    """A movement read on a bed-management screen (computer-use agent). Clear identifiers
    are pseudonymised on receipt and never stored; any extra field is refused."""

    source_system: str = Field(min_length=1, max_length=60)
    movement_ref: str = Field(min_length=1, max_length=50)
    event: Literal["A01", "A02", "A03", "A04", "A06", "A21", "A22"]
    action: Literal["INSERT", "CANCEL"] = "INSERT"
    occurred_at: AwareDatetime
    encounter_id: str = Field(min_length=1, max_length=64)
    patient_id: str = Field(min_length=1, max_length=64)
    patient_class: Literal["E", "I", "R", "O", "N"] | None = None
    uf_code: str | None = Field(default=None, max_length=20)
    room: str | None = Field(default=None, max_length=40)
    bed: str | None = Field(default=None, max_length=40)
    facility_finess: str | None = Field(default=None, pattern=r"^\d{2}[0-9AB]\d{6}$")
    sex: Literal["F", "M", "U"] | None = None
    age: int | None = Field(default=None, ge=0, le=130)
    outcome: Literal["hospitalise", "sortie", "transfert", "fugue", "deces"] | None = None


class MovementResultOut(BaseModel):
    movement_ref: str
    status: str  # applied | duplicate | ignored | rejected
    message: str
    movement_id: int | None


class MovementOut(BaseModel):
    """One journal line. ``encounter`` is the start of the pseudonym, to follow a venue."""

    id: int
    received_at: datetime
    occurred_at: datetime
    source_system: str
    movement_ref: str | None
    event: str
    event_label: str
    action: str
    status: str
    error: str | None
    encounter: str
    site_id: int | None
    unit_label: str | None
    bed_label: str | None


class MovementPageOut(BaseModel):
    items: list[MovementOut]
    total: int
    last_24h: dict[str, int]
    rejection_rate_24h: float | None


# --- forecast-engine ---


class ForecastDayOut(BaseModel):
    day: date
    horizon: str  # "J+0" .. "J+7"
    mean: float
    q10: float
    q50: float
    q90: float
    p_tension: float | None = None
    p_critique: float | None = None


class ObservedPointOut(BaseModel):
    day: date
    value: float


class ForecastSeriesOut(BaseModel):
    scope: str
    scope_key: str
    label: str
    site_id: int | None = None
    pool_id: int | None = None
    target: str
    beds_installed: int | None = None
    model: str | None = None  # model chosen for this series (arrivals, boarding)
    fallback: bool | None = None  # no candidate beat the seasonal naive reference
    values: list[ForecastDayOut]
    recent: list[ObservedPointOut] = Field(default_factory=list)


class ForecastRunOut(BaseModel):
    id: int
    as_of: date
    created_at: datetime
    model_version: str
    horizon_days: int
    age_hours: float
    stale: bool  # not computed for today, or more than 26 hours old
    models_chosen: dict[str, int]
    fallback_series: int
    common_shock_variance: float | None = None


class BacktestHeadlineOut(BaseModel):
    created_at: datetime
    last_full_day: date
    origins: int
    gates: dict[str, str]
    arrivals_mae_ratio: float | None = None
    arrivals_coverage_80: float | None = None
    beds_coverage_80: float | None = None
    beds_coverage_80_randomised: float | None = None
    boarding_mae_ratio: float | None = None


class LiscopForecastOut(BaseModel):
    scope: str
    targets: list[str]
    run: ForecastRunOut | None
    last_failure_at: datetime | None = None
    restricted_to_site: int | None = None
    synthetic: bool
    series: list[ForecastSeriesOut]
    backtest: BacktestHeadlineOut | None = None
    notes: list[str]


# --- ror-oru-export ---
