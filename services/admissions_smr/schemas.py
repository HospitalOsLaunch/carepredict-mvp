"""HTTP contracts (Pydantic v2)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from services.admissions_smr.vocab import (
    CAPACITY_REASONS,
    LOSS_REASONS,
    MENTIONS,
    REFUSAL_REASONS,
    REQUEST_SOURCES,
    ROLES,
    SPECIAL_NEEDS,
)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- auth -----------------------------------------------------------------


class LoginIn(Strict):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    site_id: int | None
    active: bool
    oidc_subject: str | None = None


class LoginOut(BaseModel):
    token: str
    user: UserOut
    group_name: str


class UserCreate(Strict):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)
    full_name: str = Field(min_length=2, max_length=200)
    password: str = Field(min_length=10, max_length=200)
    role: str
    site_id: int | None = None

    @field_validator("role")
    @classmethod
    def _role(cls, value: str) -> str:
        if value not in ROLES:
            raise ValueError("rôle inconnu")
        return value


class UserUpdate(Strict):
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    role: str | None = None
    site_id: int | None = None
    active: bool | None = None
    password: str | None = Field(default=None, min_length=10, max_length=200)
    oidc_subject: str | None = Field(default=None, max_length=255)

    @field_validator("role")
    @classmethod
    def _role(cls, value: str | None) -> str | None:
        if value is not None and value not in ROLES:
            raise ValueError("rôle inconnu")
        return value


# --- sites ----------------------------------------------------------------


class PoolOut(BaseModel):
    mention: str
    beds_installed: int
    beds_open: int
    isolation_rooms: int
    occupied: int


class SiteOut(BaseModel):
    id: int
    name: str
    finess: str | None
    city: str | None
    capabilities: list[str]
    active: bool
    pools: list[PoolOut]


class SiteCreate(Strict):
    name: str = Field(min_length=2, max_length=200)
    finess: str | None = Field(default=None, pattern=r"^\d{2}[0-9ABab]\d{6}$")
    city: str | None = Field(default=None, max_length=120)
    capabilities: list[str] = Field(default_factory=list)

    @field_validator("capabilities")
    @classmethod
    def _caps(cls, value: list[str]) -> list[str]:
        unknown = [v for v in value if v not in SPECIAL_NEEDS]
        if unknown:
            raise ValueError(f"capacités inconnues : {unknown}")
        return sorted(set(value))


class SiteUpdate(Strict):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    finess: str | None = Field(default=None, pattern=r"^\d{2}[0-9ABab]\d{6}$")
    city: str | None = Field(default=None, max_length=120)
    capabilities: list[str] | None = None
    active: bool | None = None

    @field_validator("capabilities")
    @classmethod
    def _caps(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        unknown = [v for v in value if v not in SPECIAL_NEEDS]
        if unknown:
            raise ValueError(f"capacités inconnues : {unknown}")
        return sorted(set(value))


class PoolUpsert(Strict):
    beds_installed: int = Field(ge=0, le=2000)
    beds_open: int = Field(ge=0, le=2000)
    isolation_rooms: int = Field(default=0, ge=0, le=2000)
    reason: str
    effective_date: date | None = None
    comment: str | None = Field(default=None, max_length=1000)

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        if value not in CAPACITY_REASONS:
            raise ValueError("motif inconnu")
        return value


# --- requests -------------------------------------------------------------


class RequestCreate(Strict):
    source: str
    external_ref: str | None = Field(default=None, max_length=120)
    received_at: datetime | None = None
    referrer_facility: str = Field(min_length=2, max_length=200)
    referrer_unit: str | None = Field(default=None, max_length=200)
    patient_ref: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_\-.]+$")
    patient_age: int | None = Field(default=None, ge=0, le=120)
    patient_sex: str | None = Field(default=None, pattern=r"^[FMI]$")
    mention_requested: str
    clinical_category: str | None = Field(default=None, max_length=200)
    care_level: int = Field(default=2, ge=1, le=4)
    isolation_required: bool = False
    special_needs: list[str] = Field(default_factory=list)
    desired_date: date | None = None
    site_id: int | None = None
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("source")
    @classmethod
    def _source(cls, value: str) -> str:
        if value not in REQUEST_SOURCES:
            raise ValueError("source inconnue")
        return value

    @field_validator("mention_requested")
    @classmethod
    def _mention(cls, value: str) -> str:
        if value not in MENTIONS:
            raise ValueError("mention inconnue")
        return value

    @field_validator("special_needs")
    @classmethod
    def _needs(cls, value: list[str]) -> list[str]:
        unknown = [v for v in value if v not in SPECIAL_NEEDS]
        if unknown:
            raise ValueError(f"besoins inconnus : {unknown}")
        return sorted(set(value))

    @field_validator("patient_ref")
    @classmethod
    def _no_nir(cls, value: str) -> str:
        if value.isdigit() and len(value) >= 13:
            raise ValueError("ressemble à un NIR : référence pseudonymisée attendue")
        return value


class FactorOut(BaseModel):
    code: str
    label: str
    value: float
    weight: float
    contribution: float
    detail: str


class SuggestionOut(BaseModel):
    site_id: int
    site_name: str
    eligible: bool
    blockers: list[str]
    score: float
    factors: list[FactorOut]
    safe_date: date | None
    probable_date: date | None


class RequestOut(BaseModel):
    id: int
    source: str
    external_ref: str | None
    received_at: datetime
    referrer_facility: str
    referrer_unit: str | None
    patient_ref: str
    patient_age: int | None
    patient_sex: str | None
    mention_requested: str
    clinical_category: str | None
    care_level: int
    isolation_required: bool
    special_needs: list[str]
    desired_date: date | None
    status: str
    site_id: int | None
    site_name: str | None
    proposed_date: date | None
    first_response_at: datetime | None
    closed_at: datetime | None
    refusal_reason: str | None
    loss_reason: str | None
    notes: str | None
    waiting_hours: float
    priority: float
    best: SuggestionOut | None


class EventOut(BaseModel):
    at: datetime
    kind: str
    from_status: str | None
    to_status: str | None
    detail: str | None
    actor: str | None


class PortalReplyOut(BaseModel):
    task_id: int
    status: str
    engine_used: str | None
    error: str | None
    updated_at: datetime


class RequestDetailOut(RequestOut):
    suggestions: list[SuggestionOut]
    events: list[EventOut]
    draft_message: str | None
    stay_id: int | None
    portal_reply: PortalReplyOut | None = None


class StartIn(Strict):
    site_id: int | None = None


class AccordIn(Strict):
    site_id: int
    proposed_date: date


class RefuseIn(Strict):
    reason: str
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        if value not in REFUSAL_REASONS:
            raise ValueError("motif inconnu")
        return value


class LoseIn(Strict):
    reason: str
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        if value not in LOSS_REASONS:
            raise ValueError("motif inconnu")
        return value


class ConfirmIn(Strict):
    proposed_date: date | None = None


class AdmitIn(Strict):
    admission_date: date
    planned_discharge_date: date | None = None
    care_level: int | None = Field(default=None, ge=1, le=4)


class ReorientIn(Strict):
    site_id: int


class NoteIn(Strict):
    text: str = Field(min_length=1, max_length=4000)


class ReopenIn(Strict):
    comment: str | None = Field(default=None, max_length=2000)


# --- stays ----------------------------------------------------------------


class StayOut(BaseModel):
    id: int
    site_id: int
    site_name: str
    mention: str
    patient_ref: str
    admission_date: date
    planned_discharge_date: date | None
    discharge_date: date | None
    length_of_stay: int
    care_level: int | None
    prob_within_7_days: float | None
    median_discharge_day: date | None
    plan_changes: int


class StayCreate(Strict):
    site_id: int
    mention: str
    patient_ref: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_\-.]+$")
    admission_date: date
    planned_discharge_date: date | None = None
    care_level: int | None = Field(default=None, ge=1, le=4)

    @field_validator("mention")
    @classmethod
    def _mention(cls, value: str) -> str:
        if value not in MENTIONS:
            raise ValueError("mention inconnue")
        return value


class StayUpdate(Strict):
    planned_discharge_date: date | None = None
    discharge_date: date | None = None
    clear_planned: bool = False
    care_level: int | None = Field(default=None, ge=1, le=4)


# --- forecast & dashboard -------------------------------------------------


class DayForecastOut(BaseModel):
    day: date
    expected_discharges: float
    cumulative_expected: float
    cumulative_p10: int
    cumulative_p90: int
    reserved: int
    free_expected: float
    free_p10: int
    free_p90: int
    prob_at_least_one_free: float


class PoolForecastOut(BaseModel):
    site_id: int
    site_name: str
    mention: str
    beds_open: int
    beds_installed: int
    occupied_now: int
    days: list[DayForecastOut]


class ForecastBasis(BaseModel):
    method: str
    stays_used: int
    completed_stays_used: int
    low_data_mentions: list[str]
    plan_slip_is_prior: bool
    plan_slip_samples: int


class ForecastOut(BaseModel):
    as_of: date
    horizon: int
    basis: ForecastBasis
    pools: list[PoolForecastOut]


class SiteCardOut(BaseModel):
    site_id: int
    site_name: str
    city: str | None
    beds_installed: int
    beds_open: int
    occupied: int
    occupancy_on_open: float | None
    awaiting_response: int
    oldest_waiting_hours: float | None
    discharges_next_7_days: float
    free_beds_in_7_days: float
    reserved_next_7_days: int


class GroupDashboardOut(BaseModel):
    as_of: date
    group_name: str
    beds_installed: int
    beds_open: int
    occupied: int
    occupancy_on_open: float | None
    awaiting_response: int
    responses_median_hours_30d: float | None
    sites: list[SiteCardOut]
    daily_free_beds: list[dict[str, float | str]]


# --- pilot metrics --------------------------------------------------------


class OccupancyOut(BaseModel):
    days: int
    occupied_bed_days: int
    open_bed_days: int
    installed_bed_days: int
    rate_on_open: float | None
    rate_on_installed: float | None
    avg_closed_beds: float
    closed_bed_days_by_reason: dict[str, int]


class RequestsSummaryOut(BaseModel):
    received: int
    responded: int
    response_hours_median: float | None
    response_hours_p90: float | None
    responded_within_24h: float | None
    by_status: dict[str, int]
    accord_rate: float | None
    conversion_rate: float | None
    lost_after_accord_rate: float | None
    refusal_reasons: dict[str, int]
    loss_reasons: dict[str, int]


class NorthStarOut(BaseModel):
    baseline_rate: float
    period_rate: float
    recovered_bed_days: float
    recovered_low: float | None
    recovered_high: float | None
    value_eur: float
    value_low_eur: float | None
    value_high_eur: float | None
    success_fee_eur: float
    period_days: int
    baseline_days: int
    placebo_windows: int
    included_pools: list[str]
    excluded_pools: dict[str, str]
    interval_note: str


class BaselineOut(BaseModel):
    start: date | None
    end: date | None
    frozen_at: datetime | None
    snapshot_id: int | None = None
    digest: str | None = None


class PilotMetricsOut(BaseModel):
    period_start: date
    period_end: date
    site_id: int | None
    occupancy: OccupancyOut
    requests: RequestsSummaryOut
    baseline: BaselineOut
    baseline_occupancy: OccupancyOut | None
    north_star: NorthStarOut | None
    north_star_unavailable_reason: str | None
    weekly: list[dict[str, float | str | None]]


class BacktestPointOut(BaseModel):
    as_of: date
    predicted: float
    p10: int
    p90: int
    actual: int


class BacktestOut(BaseModel):
    horizon_days: int
    points: list[BacktestPointOut]
    mae: float | None
    bias: float | None
    coverage_80: float | None
    note: str


class GroupSettingsOut(BaseModel):
    name: str
    value_per_bed_day: float
    success_fee_rate: float
    scoring_weights: dict[str, float]
    care_minutes: dict[str, float]
    baseline: BaselineOut


CARE_MINUTE_KEYS = ("1", "2", "3", "4", "entree", "sortie")


class GroupSettingsIn(Strict):
    value_per_bed_day: float | None = Field(default=None, ge=0, le=5000)
    success_fee_rate: float | None = Field(default=None, ge=0, le=1)
    scoring_weights: dict[str, float] | None = None
    care_minutes: dict[str, float] | None = None

    @field_validator("care_minutes")
    @classmethod
    def _care(cls, value: dict[str, float] | None) -> dict[str, float] | None:
        if value is None:
            return None
        unknown = set(value) - set(CARE_MINUTE_KEYS)
        if unknown:
            raise ValueError(f"clés inconnues : {sorted(unknown)}")
        if any(v < 0 or v > 1440 for v in value.values()):
            raise ValueError("minutes entre 0 et 1440")
        return value


# --- predictions ----------------------------------------------------------


class WorkloadDayOut(BaseModel):
    day: date
    census_expected: float
    known_admissions: int
    expected_new_admissions: float
    care_minutes_expected: float
    care_minutes_p10: float
    care_minutes_p90: float
    staff_minutes: float | None
    load_ratio: float | None
    prob_over_capacity: float | None
    tension: str


class PoolWorkloadOut(BaseModel):
    site_id: int
    site_name: str
    mention: str
    beds_open: int
    occupied_now: int
    staffing_configured: bool
    days: list[WorkloadDayOut]


class WorkloadOut(BaseModel):
    as_of: date
    horizon: int
    care_minutes: dict[str, float]
    plan_slip_is_prior: bool
    plan_slip_samples: int
    care_level_known_share: float | None
    pools: list[PoolWorkloadOut]


class StaffPoolOut(BaseModel):
    site_id: int
    site_name: str
    mention: str
    weekly_hours: list[float | None]
    overrides: dict[str, float]


class WeeklyStaffIn(Strict):
    hours: list[float | None] = Field(min_length=7, max_length=7)
    comment: str | None = Field(default=None, max_length=300)

    @field_validator("hours")
    @classmethod
    def _hours(cls, value: list[float | None]) -> list[float | None]:
        if any(v is not None and (v < 0 or v > 2000) for v in value):
            raise ValueError("heures entre 0 et 2000")
        return value


class DayStaffIn(Strict):
    care_hours: float | None = Field(default=None, ge=0, le=2000)
    comment: str | None = Field(default=None, max_length=300)


class WorkloadBacktestOut(BaseModel):
    points: list[dict[str, float | str]]
    mape: float | None
    bias_pct: float | None
    coverage_80: float | None
    note: str


class BaselineIn(Strict):
    start: date
    end: date


# --- imports & misc -------------------------------------------------------


class ImportIn(Strict):
    csv_text: str = Field(max_length=20_000_000)
    dry_run: bool = True


class ImportErrorOut(BaseModel):
    line: int
    column: str | None
    message: str


class ImportOut(BaseModel):
    kind: str
    dry_run: bool
    rows: int
    created: int
    updated: int
    errors: list[ImportErrorOut]
    committed: bool


class AuditOut(BaseModel):
    at: datetime
    user: str | None
    action: str
    entity: str
    entity_id: str | None
    detail: str | None


class VocabularyOut(BaseModel):
    mentions: dict[str, str]
    sources: dict[str, str]
    statuses: dict[str, str]
    refusal_reasons: dict[str, str]
    loss_reasons: dict[str, str]
    capacity_reasons: dict[str, str]
    special_needs: dict[str, str]
    roles: dict[str, str]
