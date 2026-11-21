"""Public data contract of the synthetic demonstration. Simulator tapes never enter this schema."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
