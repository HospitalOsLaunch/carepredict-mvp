"""Dagster normalization assets."""

from __future__ import annotations

from dagster import AssetExecutionContext, asset


@asset(group_name="normalization")
def canonical_events(context: AssetExecutionContext) -> str:
    """Placeholder asset for raw event normalization."""
    context.log.info("Normalization asset scaffolded")
    return "canonical.events"
