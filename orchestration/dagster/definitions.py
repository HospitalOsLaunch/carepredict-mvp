"""Dagster definitions for CarePredict pass 1."""

from __future__ import annotations

from assets import drift_metrics, features, ingestion, model_training, normalization, predictions
from dagster import Definitions, load_assets_from_modules
from jobs.full_pipeline import full_pipeline
from jobs.retraining_pipeline import retraining_pipeline
from schedules.ingestion_schedule import hourly_ingestion_schedule
from sensors.drift_sensor import drift_sensor

all_assets = load_assets_from_modules(
    [ingestion, normalization, features, model_training, predictions, drift_metrics]
)

defs = Definitions(
    assets=all_assets,
    jobs=[full_pipeline, retraining_pipeline],
    schedules=[hourly_ingestion_schedule],
    sensors=[drift_sensor],
)
