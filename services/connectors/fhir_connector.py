"""FHIR R4 connector entrypoint."""

from __future__ import annotations


SUPPORTED_RESOURCES: set[str] = {"Patient", "Encounter", "Observation", "Procedure"}


def is_supported_resource(resource_type: str) -> bool:
    """Return whether a FHIR resource type is in pass 1 scope."""
    return resource_type in SUPPORTED_RESOURCES
