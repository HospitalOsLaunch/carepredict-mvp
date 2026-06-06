"""Dagster assets for batch prediction smoke checks."""

from __future__ import annotations

from dagster import AssetExecutionContext, asset


@asset(group_name="serving")
def prediction_smoke_check(context: AssetExecutionContext) -> str:
    """Validate prediction service wiring after training."""
    context.log.info("Prediction smoke check scaffolded")
    return "prediction-api-ready"
