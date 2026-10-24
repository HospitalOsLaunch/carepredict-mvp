"""Explicit local export mapping; distinct from the aggregate Nantes contract."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, JsonValue, StrictInt, field_validator, model_validator

from hospitalos.operational.contract import Closed, Identifier, instant

from .models import Bed, Discharge, Patient, ResourcePool, Unit

Kind = Literal["unit", "bed", "patient", "pool", "discharge", "availability"]
KINDS: tuple[Kind, ...] = ("unit", "bed", "patient", "pool", "discharge", "availability")
FACT_TYPES: dict[str, type[Unit | Bed | Patient | ResourcePool | Discharge]] = {
    "unit": Unit,
    "bed": Bed,
    "patient": Patient,
    "pool": ResourcePool,
    "discharge": Discharge,
}
EVENT_FIELDS = {"event_id", "version", "event_time", "available_at"}
AVAILABILITY_FIELDS = {"resource", "target_id", "available", "observed_at", "evidence_ref"}
VALUE_MAP_FIELDS = {
    "fact.state",
    "fact.status",
    "fact.resource",
    "resource",
    "fact.medically_cleared",
    "fact.downstream_confirmed",
    "fact.documents_ready",
    "fact.escort_required",
    "fact.escort_confirmed",
    "fact.downstream_required",
    "fact.transport_required",
    "fact.transport_requested",
}


def expected_fields(kind: Kind) -> set[str]:
    if kind == "availability":
        return AVAILABILITY_FIELDS
    return EVENT_FIELDS | {f"fact.{f}" for f in FACT_TYPES[kind].model_fields if f != "kind"}


def forbidden_column(name: str) -> bool:
    # Defense in depth only: column names cannot prove that values are pseudonymous.
    name = re.sub(r"([a-z])([A-Z])", r"\1_\2", name)
    normalized = "".join(
        c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c)
    )
    tokens = set(re.findall(r"[a-z0-9]+", normalized.lower()))
    return bool(
        tokens
        & {
            "nom",
            "prenom",
            "name",
            "firstname",
            "lastname",
            "ipp",
            "nir",
            "ins",
            "dob",
            "naissance",
            "birth",
            "birthdate",
            "adresse",
            "address",
            "telephone",
            "phone",
            "email",
            "mail",
            "commentaire",
            "comment",
            "comments",
            "note",
            "notes",
            "texte",
        }
    )


def timestamp(value: JsonValue) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Explicit ISO timestamp required")
    return instant(datetime.fromisoformat(value.replace("Z", "+00:00")))


class TableMapping(Closed):
    kind: Kind
    table: Identifier
    # canonical field -> exact, flat source column. No expressions or code execution.
    columns: dict[str, Identifier]
    value_maps: dict[str, dict[str, str | bool | None]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def complete(self) -> Self:
        if set(self.columns) != expected_fields(self.kind):
            raise ValueError("Mapping must cover every field explicitly, including nullable fields")
        if len(set(self.columns.values())) != len(self.columns):
            raise ValueError("Each canonical field requires a distinct source column")
        if any(forbidden_column(c) for c in self.columns.values()):
            raise ValueError("Nominative or free-text source columns are outside this contract")
        if not set(self.value_maps) <= set(self.columns) & VALUE_MAP_FIELDS:
            raise ValueError("Only enumerated states and explicit booleans may be recoded")
        return self


class SourceProfile(Closed):
    schema_version: Literal["UNIT_SOURCE_PROFILE_1"] = "UNIT_SOURCE_PROFILE_1"
    profile_id: Identifier
    version: Annotated[StrictInt, Field(ge=1)]
    source_schema: Identifier
    hospital_id: Identifier
    unit_id: Identifier
    source: Identifier
    # Upstream declaration, NOT de-identification or authorization performed here.
    upstream_pseudonymized_ids: Literal[True]
    evaluation_mode: Literal["quality_only", "shadow"] = "quality_only"
    tables: tuple[TableMapping, ...]

    @model_validator(mode="after")
    def scope(self) -> Self:
        if {t.kind for t in self.tables} != set(KINDS) or len(self.tables) != len(KINDS):
            raise ValueError("Exactly one mapping per canonical table is required")
        if len({t.table for t in self.tables}) != len(self.tables):
            raise ValueError("Source tables must be distinct")
        return self


class SourceExport(Closed):
    schema_version: Literal["UNIT_SOURCE_EXPORT_1"] = "UNIT_SOURCE_EXPORT_1"
    source_schema: Identifier
    export_id: Identifier
    hospital_id: Identifier
    unit_id: Identifier
    source: Identifier
    exported_at: datetime
    manifest_version: Annotated[StrictInt, Field(ge=1)]
    # Supplied independently by the source: never inferred from the delivered rows.
    expected_entities: Annotated[tuple[str, ...], Field(min_length=1, max_length=400)]
    tables: dict[str, list[dict[str, JsonValue]]]

    @field_validator("exported_at", mode="before")
    @classmethod
    def iso_clock(cls, value: JsonValue) -> datetime:
        return timestamp(value)


class ColumnManifest(Closed):
    schema_version: Literal["UNIT_SOURCE_COLUMNS_1"] = "UNIT_SOURCE_COLUMNS_1"
    source_schema: Identifier
    tables: dict[str, list[str]]


class SourceIssue(Closed):
    code: Literal[
        "invalid_envelope",
        "invalid_json",
        "export_too_large",
        "scope_mismatch",
        "future_export",
        "unexpected_tables",
        "missing_tables",
        "unexpected_columns",
        "missing_columns",
        "forbidden_columns",
        "duplicate_columns",
        "row_budget_exceeded",
        "invalid_field",
        "invalid_record",
        "unknown_code",
        "clock_order",
        "future_record",
        "duplicate_record",
        "journal_rejected",
        "export_identity_conflict",
        "state_gate",
        "missing_entities",
        "unexpected_entities",
        "missing_confirmations",
        "unexpected_confirmations",
    ]
    kind: Kind | None = None
    field: str | None = None  # Canonical field name only, never a source value.
    count: int = 1


class QualityReport(Closed):
    schema_version: Literal["UNIT_SOURCE_QUALITY_1"] = "UNIT_SOURCE_QUALITY_1"
    status: Literal["REJECTED", "OBSERVATION_ONLY", "SHADOW_EVALUATED"]
    # This is not a Nantes Gate A decision or a clinical deployment authorization.
    receipt_at: datetime
    evaluation_mode: Literal["quality_only", "shadow"]
    state_ready: bool | None = None
    shadow_episode_created: bool = False
    profile_fingerprint: str
    content_fingerprint: str
    records_by_kind: dict[str, int]
    expected_entities: int | None = None
    delivered_entities: int | None = None
    missing_values_by_field: dict[str, int] = Field(default_factory=dict)
    issues: tuple[SourceIssue, ...] = ()
    state_gate_counts: dict[str, int] = Field(default_factory=dict)
    max_fact_age_seconds: float | None = None
    max_source_delay_seconds: float | None = None
    max_resource_age_seconds: float | None = None
    export_transfer_seconds: float | None = None
    commands_emitted: Literal[0] = 0
    clinical_validation: Literal[False] = False
