"""Public data contract of the synthetic demonstration. Simulator tapes never enter this schema."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Context(Contract):
    id: str
    label: str
    feed: Literal["full", "partial", "delayed"]
    ward_count: int


class Contexts(Contract):
    contexts: list[Context]
    model_version: str


class Ward(Contract):
    id: str
    label: str
    beds: int


Objective = Literal["transfer_queue", "bed_wait", "uncovered_care"]
Kind = Literal["reference", "transport", "cleaning", "staffing", "smr", "beds"]


PlanKind = Literal[
    "discharge",
    "admission",
    "replacement",
    "redeployment",
    "reinforcement",
    "transport",
    "cleaning",
    "smr",
    "beds",
]


class PlanAction(Contract):
    id: str
    label: str
    kind: PlanKind
    ward_id: str
    unit: str
    quantity: int = 1
    start_hour: int = 12
    end_hour: int = 16
    cost_eur: int = 0
    eligible: bool
    constraint: str


class PlanMetrics(Contract):
    transfer_queue: float
    bed_wait_patient_hours: float
    uncovered_ide_minutes: float
    uncovered_as_minutes: float
    transport_used: float
    beds_cleaned: float
    smr_transfers: float
    open_beds: float
    available_beds: float
    admissions: float
    discharges: float
    redirected_patients: float
    admission_queue_at_16: float
    named_admissions: int
    named_discharges: int


class WardImpact(Contract):
    ward_id: str
    transfer_queue: float
    admissions: float
    redirected_patients: float
    care_minutes: float
    transport_used: float
    beds_cleaned: float
    smr_transfers: float
    available_beds: float


class WardMetrics(Contract):
    transfer_queue: float
    bed_wait_patient_hours: float
    uncovered_ide_minutes: float
    uncovered_as_minutes: float
    admissions: float
    redirected_patients: float


class PlanEvaluation(Contract):
    context_id: str | None = None
    ward_id: str | None = None
    id: str
    action_ids: list[str]
    feasible: bool
    conflicts: list[str]
    cost_eur: int
    metrics: PlanMetrics | None
    ward_metrics: WardMetrics | None = None
    realized: dict[str, float]
    case_hours: dict[str, int | None] = Field(default_factory=dict)
    access_warnings: list[str] = Field(default_factory=list)
    ward_impacts: list[WardImpact] = Field(default_factory=list)


class PlanSearch(Contract):
    evaluated: int
    examined: int
    feasible: int
    recommendable: int
    scope_size: int
    complete: bool


class WardCase(Contract):
    id: str
    kind: Literal["admission", "discharge"]
    eligible: bool
    available_hour: int
    scheduled_hour: int | None


class WardState(Contract):
    context_id: str
    ward_id: str
    as_of_hour: Literal[12] = 12
    capacity_beds: int
    available_beds: float
    admission_queue: float
    transfer_queue: float
    cases: list[WardCase]


class PlanMenu(Contract):
    context_id: str | None = None
    ward_state: WardState | None = None
    ward_id: str | None = None
    objective: Objective
    actions: list[PlanAction]
    reference: PlanEvaluation
    recommendations: list[PlanEvaluation]
    search: PlanSearch
    budget_eur: int
    example_action_ids: list[str] = Field(default_factory=list)
    scope_ids: list[str] = Field(default_factory=list)


class ReconstructedPlan(Contract):
    plan: PlanEvaluation
    reconstructed_queue: float


class PlanReport(Contract):
    actual_metrics: PlanMetrics | None
    realized: dict[str, float] | None
    case_hours: dict[str, int | None] | None = None
    alternatives: list[ReconstructedPlan]


class PlanRequest(Contract):
    action_ids: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(max_length=128)
    objective: Objective

    @field_validator("action_ids")
    @classmethod
    def unique_actions(cls, actions: list[str]) -> list[str]:
        if len(actions) != len(set(actions)):
            raise ValueError("Une action identifiée ne peut être engagée deux fois.")
        return sorted(actions)


class PlanPreview(PlanRequest):
    context_id: str | None = Field(default=None, min_length=1, max_length=48)
    ward_id: str | None = Field(default=None, max_length=48)


class PlanConfirmation(PlanPreview):
    preview_id: str | None = Field(default=None, min_length=1, max_length=64)
    scope_ids: list[Annotated[str, Field(min_length=1, max_length=64)]] | None = Field(
        default=None, max_length=128
    )

    @field_validator("scope_ids")
    @classmethod
    def unique_scope(cls, ids: list[str] | None) -> list[str] | None:
        return None if ids is None else cls.unique_actions(ids)


class Option(Contract):
    id: str
    label: str
    kind: Kind
    ward_id: str | None
    forecast: float
    jepa_forecast: float | None
    eligible: bool = True
    constraint: str | None = None
    cost_eur: int | None = None
    uncovered_ide_minutes: float | None = None
    uncovered_as_minutes: float | None = None
    bed_wait_patient_hours: float | None = None
    by_ward: list[float]
    reconstruction: float | None = None
    reconstructed_by_ward: list[float] | None = None


class Observation(Contract):
    sample_hour: int
    published_hour: int
    observed_stock: float | None
    by_ward: list[float | None]
    visible_components: int
    total_components: int


class Entry(Contract):
    ward_id: str | None = None
    hour: int
    event: Literal["opened", "confirmed", "awaiting_report", "report_received"]
    option_id: str | None = None


class Session(Contract):
    id: str
    context: Context
    phase: Literal["planning", "confirmed", "awaiting_report", "review"]
    hour: int
    decision_hour: Literal[12] = 12
    target_hour: Literal[16] = 16
    publication_hour: int
    model_version: str
    morning_plan: list[str]
    wards: list[Ward]
    reference_id: str
    selected_id: str | None = None
    decision_objective: Objective | None = None
    decision_ward_id: str | None = None
    plan_version: str | None = None
    confirmed_plan: PlanEvaluation | None = None
    plan_snapshot: PlanMenu | None = None
    plan_report: PlanReport | None = None
    options: list[Option]
    observation: Observation | None = None
    journal: list[Entry]


class Start(Contract):
    context_id: str = Field(min_length=1, max_length=48)


class Confirm(Contract):
    option_id: str = Field(min_length=1, max_length=48)
    objective: Objective | None = None


class Advance(Contract):
    from_hour: int = Field(strict=True, ge=12, le=16)
