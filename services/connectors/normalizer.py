"""Normalizer entrypoint for raw SIH events."""

from __future__ import annotations


CANONICAL_TOPIC = "canonical.events"


def canonical_topic() -> str:
    """Return the canonical event topic name."""
    return CANONICAL_TOPIC
