"""Canonical schema smoke tests."""

from __future__ import annotations

from datetime import UTC, datetime

from services.connectors.schemas.canonical import CanonicalCareLoad


def test_canonical_care_load_accepts_valid_payload() -> None:
    payload = CanonicalCareLoad(
        hospital_id="hosp-001",
        service_id="urg-001",
        source_system="synthetic",
        received_at=datetime.now(tz=UTC),
        measured_at=datetime.now(tz=UTC),
        siips_score=42.0,
        patient_count=24,
    )

    assert payload.service_id == "urg-001"
