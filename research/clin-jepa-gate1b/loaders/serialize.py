"""Deterministic, leak-guarded SPARCS stay serialization for Gate 1-B."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd

from loaders.sparcs_adapter import (
    APR_FEATURES,
    FORBIDDEN_CANONICAL_FEATURES,
    LEAK_PRONE_COLUMNS,
)


@dataclass(frozen=True, slots=True)
class SerializationField:
    """One preregistered canonical field and its stable display label."""

    name: str
    label: str


BASE_SERIALIZE_FIELDS = (
    SerializationField("age_group", "Age"),
    SerializationField("gender", "Sex"),
    SerializationField("type_admission", "Admission"),
    SerializationField("ed_indicator", "ED"),
    SerializationField("apr_drg", "Diagnosis group"),
    SerializationField("apr_medsurg", "Med/Surg"),
    SerializationField("ccsr_diagnosis", "Clinical category"),
    SerializationField("health_service_area", "Region"),
    SerializationField("payment_typology", "Payer"),
)
APR_SERIALIZE_FIELDS = (
    SerializationField("apr_severity", "Severity"),
    SerializationField("apr_risk_mortality", "Mortality risk"),
)
SERIALIZE_FIELDS = BASE_SERIALIZE_FIELDS

_TARGET_COLUMN_NAMES = frozenset(
    name for name, reason in LEAK_PRONE_COLUMNS.items() if "target" in reason
)
_UNKNOWN_VALUES = frozenset({"", "unknown", "nan", "none", "<na>", "null"})


class SerializationLeakError(ValueError):
    """Raised when a value with target provenance reaches serialized text."""


def serialization_fields(*, include_apr: bool = False) -> tuple[SerializationField, ...]:
    """Return the fixed field contract; APR risk fields are opt-in only."""
    fields = BASE_SERIALIZE_FIELDS + (APR_SERIALIZE_FIELDS if include_apr else ())
    names = {field.name for field in fields}
    forbidden = set(LEAK_PRONE_COLUMNS) | FORBIDDEN_CANONICAL_FEATURES
    leaked = names.intersection(forbidden)
    if leaked:
        raise AssertionError(f"leak-prone fields entered serialization: {sorted(leaked)}")
    if not include_apr and names.intersection(APR_FEATURES):
        raise AssertionError("APR fields entered default no_apr serialization")
    return fields


def serialized_field_names(*, include_apr: bool = False) -> tuple[str, ...]:
    """Expose the exact canonical provenance of serialized values for tests/audit."""
    return tuple(field.name for field in serialization_fields(include_apr=include_apr))


def serialize_structured(row: Mapping[str, object], include_apr: bool = False) -> str:
    """Serialize one stay as the preregistered structured primary representation."""
    parts = ["Inpatient admission."]
    for field in serialization_fields(include_apr=include_apr):
        value = _clean_value(row.get(field.name))
        if value is not None:
            parts.append(f"{field.label}: {value}.")
    text = " ".join(parts)
    _assert_no_target_provenance(row, text)
    return text


def serialize_fluent(row: Mapping[str, object], include_apr: bool = False) -> str:
    """Serialize one stay as the preregistered fluent robustness ablation."""
    values = {
        field.name: _clean_value(row.get(field.name))
        for field in serialization_fields(include_apr=include_apr)
    }
    sentences = ["This is an inpatient admission."]
    _append(sentences, values["age_group"], "The age group was {}.")
    _append(sentences, values["gender"], "The recorded sex was {}.")
    _append(sentences, values["type_admission"], "The admission type was {}.")
    _append(sentences, values["ed_indicator"], "The emergency department indicator was {}.")
    _append(sentences, values["apr_drg"], "The diagnosis group was {}.")
    _append(sentences, values["apr_medsurg"], "The medical or surgical class was {}.")
    _append(sentences, values["ccsr_diagnosis"], "The clinical category was {}.")
    _append(sentences, values["health_service_area"], "The hospital region was {}.")
    _append(sentences, values["payment_typology"], "The payer category was {}.")
    if include_apr:
        _append(sentences, values["apr_severity"], "The APR severity was {}.")
        _append(sentences, values["apr_risk_mortality"], "The APR mortality risk was {}.")
    text = " ".join(sentences)
    _assert_no_target_provenance(row, text)
    return text


def _clean_value(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    cleaned = str(value).strip()
    if cleaned.lower() in _UNKNOWN_VALUES:
        return None
    return cleaned


def _append(sentences: list[str], value: str | None, template: str) -> None:
    if value is not None:
        sentences.append(template.format(value))


def _assert_no_target_provenance(row: Mapping[str, object], text: str) -> None:
    for column, raw_value in row.items():
        if _normalize_column(column) not in _TARGET_COLUMN_NAMES:
            continue
        value = _clean_value(raw_value)
        if value is not None and value in text:
            raise SerializationLeakError(
                f"target-derived value from {column!r} reached serialized text"
            )


def _normalize_column(column: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(column).strip().lower()).strip("_")
