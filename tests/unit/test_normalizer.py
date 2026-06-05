"""Normalizer scaffolding tests."""

from __future__ import annotations

from services.connectors.normalizer import canonical_topic


def test_canonical_topic() -> None:
    assert canonical_topic() == "canonical.events"
