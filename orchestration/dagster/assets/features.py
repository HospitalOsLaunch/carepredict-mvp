"""Dagster feature assets."""

from __future__ import annotations

from dagster import AssetExecutionContext, asset


@asset(group_name="features")
def dbt_staging(context: AssetExecutionContext, canonical_events: str) -> str:
    """Placeholder asset for dbt staging."""
    context.log.info("dbt staging scaffolded from %s", canonical_events)
    return "dbt_staging"


@asset(group_name="features")
def dbt_marts(context: AssetExecutionContext, dbt_staging: str) -> str:
    """Placeholder asset for dbt marts."""
    context.log.info("dbt marts scaffolded from %s", dbt_staging)
    return "dbt_marts"


@asset(group_name="features")
def feast_materialize(context: AssetExecutionContext, dbt_marts: str) -> str:
    """Placeholder asset for Feast materialization."""
    context.log.info("Feast materialization scaffolded from %s", dbt_marts)
    return "feast_online_store"
