"""P1 contracts: PublicSnapshot, ActionSpec/Plan, ScenarioLocks, ForecastBundle, Recommendation.

Closed, frozen Pydantic models (extra fields are refused). Times are UTC instants;
Europe/Paris is a display/civil-resolution concern (see clock.py). ``None`` always means
unknown and is never converted to zero or to "available". Nothing in this module can hold a
private future (realised discharge time, ready_h, dis_h, outcome labels).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Annotated, Any, Literal, Self

from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator

from hospitalos.operational.contract import Closed, Identifier

from .clock import PARIS, resolve_local, utc

SNAPSHOT_SCHEMA = "DS_PUBLIC_SNAPSHOT_1"
PLAN_SCHEMA = "DS_PLAN_1"
LOCKS_SCHEMA = "DS_SCENARIO_LOCKS_1"
FORECAST_SCHEMA = "DS_FORECAST_BUNDLE_1"
RECOMMENDATION_SCHEMA = "DS_RECOMMENDATION_1"

Count = Annotated[StrictInt, Field(ge=0)]
Skill = Literal["IDE", "AS"]
Status = Literal[
    "RECOMMENDATION_READY",
    "NO_ACTION_PREFERRED",
    "INSUFFICIENT_DATA",
    "INFEASIBLE",
    "HYPOTHETICAL_ONLY",
    "INVALIDATED",
]
Mode = Literal["auto", "manual"]


def _utc(value: datetime | None) -> datetime | None:
    return utc(value) if value is not None else None


class Distribution(Closed):
    """Finite synthetic distribution over whole hours (integer weights, exact arithmetic).

    It is a declared hypothesis on synthetic data, not a calibration on real data.
    """

    support: Annotated[tuple[StrictInt, ...], Field(min_length=1, max_length=12)]
    weights: Annotated[tuple[Annotated[StrictInt, Field(gt=0)], ...], Field(min_length=1)]

    @model_validator(mode="after")
    def shape(self) -> Self:
        if len(self.support) != len(self.weights):
            raise ValueError("support and weights must have the same length")
        if any(v < 0 for v in self.support):
            raise ValueError("delays are non-negative whole hours")
        return self

    @classmethod
    def point(cls, value: int) -> Distribution:
        return cls(support=(value,), weights=(1,))


# --------------------------------------------------------------------------- observations


ObservationKind = Literal[
    "bed",
    "stay",
    "medical_authorization",
    "discharge_logistics",
    "readiness_estimate",
    "planned_departure",
    "care_profile",
    "care_task",
    "obstacle",
    "admission_request",
    "staff_shift",
    "roster_coverage",
    "reinforcement_option",
    "team_capacity",
]


class Observation(Closed):
    """One timestamped public fact. ``available_at`` is when the unit could know it."""

    obs_id: Identifier
    kind: ObservationKind
    subject: Identifier
    event_time: datetime
    available_at: datetime
    source: Identifier
    synthetic: Literal[True] = True
    value: dict[str, Any]

    @field_validator("event_time", "available_at")
    @classmethod
    def _instants(cls, value: datetime) -> datetime:
        return utc(value)

    @model_validator(mode="after")
    def clocks(self) -> Self:
        if self.available_at < self.event_time:
            raise ValueError("An observation cannot be available before its event time")
        return self


class Provenance(Closed):
    obs_id: str
    source: str
    event_time: datetime
    available_at: datetime


# --------------------------------------------------------------------------- snapshot entities


class BedState(Closed):
    bed_id: Identifier
    status: Literal["occupied", "clean", "dirty", "cleaning", "closed", "unknown"]
    capabilities: tuple[Identifier, ...] = ()
    cleaning: Distribution | None = None  # hours of cleaning work (public estimate)
    provenance: Provenance


class CareTask(Closed):
    task_id: Identifier
    skill: Skill
    start: datetime
    minutes: Annotated[StrictInt, Field(gt=0, le=60)]
    staff_required: Annotated[StrictInt, Field(ge=1, le=4)] = 1
    status: Literal["known", "estimated"]

    @field_validator("start")
    @classmethod
    def _start(cls, value: datetime) -> datetime:
        return utc(value)


class CareProfile(Closed):
    """Estimated recurring care in staff-minutes per hour, by skill (synthetic)."""

    skill: Skill
    day_minutes_per_hour: Count
    night_minutes_per_hour: Count
    status: Literal["known", "estimated"] = "estimated"


class StayState(Closed):
    stay_id: Identifier  # pseudonymous
    bed_id: Identifier | None
    medical_authorization: Literal["authorized", "not_authorized", "revoked", "unknown"]
    destination: Literal["home", "facility", "unknown"]
    transport_need: Literal["none", "seated", "stretcher", "unknown"]
    transport_lead: Distribution | None = None  # booking lead time, public estimate
    ready_earliest: datetime | None = None  # public estimate, not a certain future
    ready_delay: Distribution | None = None
    planned_departure: datetime | None = None  # habitual plan = forecast, not a certainty
    care: tuple[CareProfile, ...] = ()
    tasks: tuple[CareTask, ...] = ()
    obstacles: tuple[Identifier, ...] = ()
    provenance: dict[str, Provenance]

    @field_validator("ready_earliest", "planned_departure")
    @classmethod
    def _instants(cls, value: datetime | None) -> datetime | None:
        return _utc(value)


class AdmissionRequest(Closed):
    request_id: Identifier
    requirements: tuple[Identifier, ...] = ()
    expected_arrival: datetime
    arrival_delay: Distribution
    care: tuple[CareProfile, ...]
    admission_task_minutes: Count
    provenance: Provenance

    @field_validator("expected_arrival")
    @classmethod
    def _instant(cls, value: datetime) -> datetime:
        return utc(value)


class StaffShift(Closed):
    staff_id: Identifier
    skill: Skill
    start: datetime
    end: datetime
    status: Literal["scheduled", "confirmed"]

    @field_validator("start", "end")
    @classmethod
    def _instants(cls, value: datetime) -> datetime:
        return utc(value)


class RosterCoverage(Closed):
    """Declares the roster of a skill complete over a window. Absent => roster unknown."""

    skill: Skill
    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def _instants(cls, value: datetime) -> datetime:
        return utc(value)


class ReinforcementOption(Closed):
    option_id: Identifier
    skill: Skill
    start: datetime
    end: datetime
    source: Literal["internal_pool", "interim", "shared_unit"]
    confirmation: Literal["confirmed", "requested", "not_requested", "unknown"]
    lending_unit: Identifier | None = None
    lending_unit_scheduled: Count | None = None
    lending_unit_minimum: Count | None = None

    @field_validator("start", "end")
    @classmethod
    def _instants(cls, value: datetime) -> datetime:
        return utc(value)

    @property
    def hours(self) -> int:
        return int((self.end - self.start) / timedelta(hours=1))


class TeamCapacity(Closed):
    team: Literal["transport", "cleaning"]
    start: datetime
    end: datetime
    capacity: Count | None  # concurrent jobs per hour; None = unknown
    external_commitments: Count | None  # committed outside this unit; None = unknown

    @field_validator("start", "end")
    @classmethod
    def _instants(cls, value: datetime) -> datetime:
        return utc(value)


class UnitInfo(Closed):
    unit_id: Identifier
    timezone: Literal["Europe/Paris"] = "Europe/Paris"
    profile_id: Identifier
    profile_version: Identifier


class PublicSnapshot(Closed):
    """What the unit knows at ``as_of``. Contains no private realisation."""

    schema_version: Literal["DS_PUBLIC_SNAPSHOT_1"] = SNAPSHOT_SCHEMA
    snapshot_id: str
    fingerprint: str
    as_of: datetime
    synthetic: Literal[True] = True
    unit: UnitInfo
    stays: tuple[StayState, ...]
    beds: tuple[BedState, ...]
    admissions: tuple[AdmissionRequest, ...]
    shifts: tuple[StaffShift, ...]
    roster_coverage: tuple[RosterCoverage, ...]
    reinforcements: tuple[ReinforcementOption, ...]
    teams: tuple[TeamCapacity, ...]
    issues: tuple[str, ...] = ()  # contradictions / missing data, explicit
    excluded_observations: dict[str, int] = {}

    @field_validator("as_of")
    @classmethod
    def _as_of(cls, value: datetime) -> datetime:
        value = utc(value)
        if value.minute or value.second or value.microsecond:
            raise ValueError("This prototype requires as_of on a whole hour")
        return value


# --------------------------------------------------------------------------- actions and plans

ActionType = Literal[
    "coordinate_discharge", "reinforcement", "locked_discharge", "locked_extension"
]


class ActionSpec(Closed):
    action_id: str
    type: ActionType
    target: Identifier
    window_start: datetime
    window_end: datetime
    preconditions: tuple[str, ...]
    resources: tuple[str, ...]
    reinforcement_hours: Count = 0
    interventions: Count = 1
    validator: Literal["cadre_de_sante", "medecin", "gestionnaire_de_lits"]
    depends_on: tuple[str, ...] = ()
    idempotency_key: str
    valid_until: datetime
    origin: Literal["auto", "manual_lock"]
    basis: Literal[
        "observed_authorization", "validated_instruction", "hypothesis_only", "resource_option"
    ]
    conditional: StrictBool = False  # e.g. reinforcement requested but not confirmed

    @field_validator("window_start", "window_end", "valid_until")
    @classmethod
    def _instants(cls, value: datetime) -> datetime:
        return utc(value)


class Plan(Closed):
    schema_version: Literal["DS_PLAN_1"] = PLAN_SCHEMA
    plan_id: str
    snapshot_id: str
    snapshot_fingerprint: str
    mode: Mode
    label: str
    actions: tuple[ActionSpec, ...]
    locked_action_ids: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()

    @property
    def is_baseline(self) -> bool:
        return not self.actions

    @property
    def reinforcement_hours(self) -> int:
        return sum(a.reinforcement_hours for a in self.actions)

    @property
    def interventions(self) -> int:
        return sum(a.interventions for a in self.actions if a.origin == "auto")


# --------------------------------------------------------------------------- manual locks


class CivilDeadline(Closed):
    """'Demain 20 h' style deadline. Resolution is explicit, never truncated to the horizon."""

    day_offset: Annotated[StrictInt, Field(ge=0, le=2)] = 1
    local_time: time
    fold: Literal[0, 1] | None = None

    def resolve(self, as_of: datetime) -> datetime:
        local_date: date = utc(as_of).astimezone(PARIS).date() + timedelta(days=self.day_offset)
        return resolve_local(local_date, self.local_time, PARIS, self.fold)


class LockedDischarge(Closed):
    kind: Literal["discharge_at"] = "discharge_at"
    stay_id: Identifier
    at: datetime
    basis: Literal["validated_instruction", "hypothesis_only"]

    @field_validator("at")
    @classmethod
    def _at(cls, value: datetime) -> datetime:
        return utc(value)


class LockedExtension(Closed):
    """Presence of a stay prolonged by t hours from a visible reference time."""

    kind: Literal["extend_presence"] = "extend_presence"
    stay_id: Identifier
    reference_time: datetime
    extension_hours: Annotated[StrictInt, Field(ge=0, le=24)]
    basis: Literal["validated_instruction", "hypothesis_only"]

    @field_validator("reference_time")
    @classmethod
    def _ref(cls, value: datetime) -> datetime:
        return utc(value)

    @property
    def target_time(self) -> datetime:
        return self.reference_time + timedelta(hours=self.extension_hours)


class LockedReinforcement(Closed):
    kind: Literal["reinforcement"] = "reinforcement"
    option_id: Identifier
    include: StrictBool


Lock = Annotated[
    LockedDischarge | LockedExtension | LockedReinforcement, Field(discriminator="kind")
]


class ScenarioLocks(Closed):
    schema_version: Literal["DS_SCENARIO_LOCKS_1"] = LOCKS_SCHEMA
    locks: tuple[Lock, ...] = ()
    deadline: CivilDeadline | None = None
    search_complements: StrictBool = True


# --------------------------------------------------------------------------- forecasts


class HourPoint(Closed):
    """One hour of a trajectory, expected over forecast scenarios (native units)."""

    hour_index: int
    start_utc: datetime
    local_label: str
    staff_scheduled: dict[str, float]
    staff_reinforcement: dict[str, float]
    staff_required: dict[str, float]
    demand_minutes: dict[str, float]
    uncovered_in_unit_minutes: float
    uncovered_waiting_minutes: float
    simultaneity_shortfall_minutes: float
    waiting_patients: float
    clean_free_beds: float
    logistic_blockers: float
    pressure_score: float | None


class PlanMetrics(Closed):
    uncovered_care_minutes: float
    uncovered_in_unit_minutes: float
    uncovered_waiting_minutes: float
    uncovered_by_skill: dict[str, float]
    simultaneity_shortfall_minutes: float
    waiting_patient_hours: float
    admissions_by_end: float
    departures_by_end: float
    beds_returned: float
    reinforcement_hours: int
    interventions: int
    peak_pressure: float | None
    peak_pressure_hour: int | None
    hours_above_threshold: float | None
    worst_scenario_uncovered_minutes: float
    best_scenario_uncovered_minutes: float
    max_total_staff_required: dict[str, float]
    max_additional_staff_required: dict[str, float]


class PlanEvaluation(Closed):
    plan: Plan
    admissible: bool
    violations: tuple[str, ...]
    warnings: tuple[str, ...]
    conditional_on: tuple[str, ...]
    metrics: PlanMetrics
    trajectory: tuple[HourPoint, ...]
    confirmed_only: PlanMetrics | None = None  # same plan without unconfirmed reinforcement
    effect_onset_hour: int | None = None
    per_scenario_uncovered: tuple[float, ...]


class SearchReport(Closed):
    enumerated: int
    evaluated: int
    limit: int
    complete: bool
    filter_rules: tuple[str, ...]
    rejected: dict[str, str]  # candidate/option -> reason


class BackendInfo(Closed):
    name: str
    version: str
    code_sha256: str
    reads_private: bool
    product_allowed: bool


class ForecastBundle(Closed):
    schema_version: Literal["DS_FORECAST_BUNDLE_1"] = FORECAST_SCHEMA
    bundle_id: str
    backend: BackendInfo
    config: dict[str, Any]
    snapshot_id: str
    snapshot_fingerprint: str
    horizon_start: datetime
    horizon_end: datetime
    horizon_hours: int
    selection_seeds: tuple[int, ...]
    seed_role: Literal["selection_in_sample"] = "selection_in_sample"
    assumptions: tuple[str, ...]
    search: SearchReport
    evaluations: tuple[PlanEvaluation, ...]
    score: dict[str, Any]


class Recommendation(Closed):
    schema_version: Literal["DS_RECOMMENDATION_1"] = RECOMMENDATION_SCHEMA
    recommendation_id: str
    status: Status
    scientific_status: Literal["PROTOTYPE_UNVALIDATED"] = "PROTOTYPE_UNVALIDATED"
    clinical_validation: Literal[False] = False
    g2: Literal["NO-GO"] = "NO-GO"
    synthetic: Literal[True] = True
    mode: Mode
    created_at: datetime
    valid_until: datetime
    snapshot_id: str
    snapshot_fingerprint: str
    objective_version: str
    engine_version: str
    reasons: tuple[str, ...]
    conditions: tuple[str, ...]
    uncertainties: tuple[str, ...]
    diagnostics: tuple[str, ...]
    approvable: bool
    baseline_plan_id: str | None
    primary_plan_id: str | None
    alternative_plan_id: str | None
    locked_plan_id: str | None = None
    locks: ScenarioLocks | None = None
    bundle: ForecastBundle | None


class ReviewResult(Closed):
    review_id: str
    recommendation_id: str
    decision: Literal["approve", "reject", "modify"]
    outcome: Literal["APPROVED_IN_DEMO", "REJECTED", "MODIFY_REQUESTED", "INVALIDATED", "REFUSED"]
    reasons: tuple[str, ...]
    recompute_required: bool
    external_command_sent: Literal[False] = False
    lifecycle: dict[str, str]  # request/approval/reservation/execution/result, kept separate
    reservations: tuple[str, ...]
    idempotency_key: str
    at: datetime
