"""FHIR parser scaffolding tests."""

from __future__ import annotations

from services.connectors.fhir_connector import is_supported_resource


def test_supported_fhir_resource() -> None:
    assert is_supported_resource("Encounter")
