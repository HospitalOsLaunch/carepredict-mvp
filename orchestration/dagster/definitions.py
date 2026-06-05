"""Dagster definitions for CarePredict pass 1."""

from __future__ import annotations

from dagster import Definitions, load_assets_from_modules

from assets import features, ingestion, normalization
from jobs.full_pipeline import full_pipeline
from schedules.ingestion_schedule import hourly_ingestion_schedule


all_assets = load_assets_from_modules([ingestion, normalization, features])

defs = Definitions(
    assets=all_assets,
    jobs=[full_pipeline],
    schedules=[hourly_ingestion_schedule],
)
