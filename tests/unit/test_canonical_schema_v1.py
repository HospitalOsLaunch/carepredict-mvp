"""Tests for Canonical Schema v1 (HOS-002).

Covers: version/metadata exposure, frozen-core fingerprint (compatibility gate),
valid fixtures, and the negative/fail-closed cases for every violation code.
Runs fully offline (stdlib + PyYAML).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from services.connectors.schemas.canonical_schema import (
    FROZEN_CORE_FINGERPRINT,
    SCHEMA_VERSION,
    ViolationCode,
    core_fingerprint,
    load_canonical_schema,
    stamp_provenance,
    validate_record,
)

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "canonical"


def _load(name: str) -> Any:
    with (_FIXTURES / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="module")
def spec():  # type: ignore[no-untyped-def]
    return load_canonical_schema()


def test_metadata_exposed(spec) -> None:  # type: ignore[no-untyped-def]
    assert SCHEMA_VERSION == "1.0.0"
    assert spec.version == "1.0.0"
    assert spec.timezone == "Europe/Paris"
    assert spec.extensions_status == "closed"
    assert set(spec.domains) == {"flow", "capacity", "staffing", "care_load", "actions"}
    assert set(spec.temporal) == {"event_time", "available_at"}


def test_core_fingerprint_frozen(spec) -> None:  # type: ignore[no-untyped-def]
    # Any change to the frozen core without bumping SCHEMA_VERSION + this pin
    # must break this test (HOS-002 acceptance: core change => new version).
    assert core_fingerprint(spec) == FROZEN_CORE_FINGERPRINT


def test_every_field_has_type_and_sensitivity(spec) -> None:  # type: ignore[no-untyped-def]
    for domain in spec.domains.values():
        for field_spec in domain.fields.values():
            assert field_spec.type
            assert field_spec.sensitivity is not None
    # No forbidden-sensitivity field may exist in the canonical core.
    for domain in spec.domains.values():
        for field_spec in domain.fields.values():
            assert field_spec.sensitivity.value != "forbidden"


def test_valid_fixtures_pass(spec) -> None:  # type: ignore[no-untyped-def]
    for entry in _load("valid_records.json"):
        violations = validate_record(spec, entry["domain"], entry["record"])
        assert violations == [], f"{entry['domain']} should be valid, got {violations}"


@pytest.mark.parametrize("entry", _load("invalid_records.json"), ids=lambda e: e["case"])
def test_invalid_fixtures_flagged(entry: dict[str, Any]) -> None:
    spec = load_canonical_schema()
    violations = validate_record(spec, entry["domain"], entry["record"])
    assert violations, f"{entry['case']} should produce a violation"
    codes = {v.code for v in violations}
    assert ViolationCode(entry["expected_code"]) in codes, (
        f"{entry['case']}: expected {entry['expected_code']}, got {sorted(c.value for c in codes)}"
    )
    if entry["expected_field"]:
        assert any(v.field == entry["expected_field"] for v in violations)


def test_determinism(spec) -> None:  # type: ignore[no-untyped-def]
    entry = _load("invalid_records.json")[0]
    first = validate_record(spec, entry["domain"], entry["record"])
    second = validate_record(spec, entry["domain"], entry["record"])
    assert first == second
    # Sorted / stable ordering.
    assert first == sorted(first)


def test_no_sensitive_value_echoed(spec) -> None:  # type: ignore[no-untyped-def]
    # The free-text fixture carries a fake name; ensure it never appears in output.
    entry = next(e for e in _load("invalid_records.json") if e["case"] == "unknown_field_free_text")
    violations = validate_record(spec, entry["domain"], entry["record"])
    blob = json.dumps([v.to_dict() for v in violations])
    assert "Jean Dupont" not in blob
    assert "chambre" not in blob


def test_stamp_provenance(spec) -> None:  # type: ignore[no-untyped-def]
    stamped = stamp_provenance({"forecast": 1.0}, run_id="run-abc")
    assert stamped["schema_version"] == "1.0.0"
    assert stamped["run_id"] == "run-abc"
    assert stamped["forecast"] == 1.0


def test_optional_field_absent_is_valid(spec) -> None:  # type: ignore[no-untyped-def]
    record = {
        "hospital_id": "chu-nantes",
        "service_id": "urg-001",
        "source_system": "sih",
        "event_time": "2026-08-11T08:00:00+02:00",
        "available_at": "2026-08-11T08:05:00+02:00",
        "siips_score": 42.0,
        "patient_count": 24,
    }  # aas_score (nullable/optional) omitted
    assert validate_record(spec, "care_load", record) == []


def test_bool_rejected_as_integer(spec) -> None:  # type: ignore[no-untyped-def]
    record = {
        "hospital_id": "chu-nantes",
        "service_id": "urg-001",
        "source_system": "sih",
        "event_time": "2026-08-11T08:00:00+02:00",
        "available_at": "2026-08-11T08:05:00+02:00",
        "admissions": True,
        "discharges": 3,
        "occupancy": 22,
    }
    violations = validate_record(spec, "flow", record)
    assert any(
        v.code == ViolationCode.TYPE_MISMATCH and v.field == "admissions" for v in violations
    )
