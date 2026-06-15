"""Hourly ingestion schedule."""

from __future__ import annotations

from dagster import ScheduleDefinition
from jobs.full_pipeline import full_pipeline

hourly_ingestion_schedule = ScheduleDefinition(
    job=full_pipeline,
    cron_schedule="0 * * * *",
    name="hourly_ingestion_schedule",
)
