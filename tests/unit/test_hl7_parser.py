"""HL7 parser scaffolding tests."""

from __future__ import annotations

from services.connectors.hl7v2_connector import is_supported_message


def test_supported_hl7_message() -> None:
    assert is_supported_message("ADT^A01")
