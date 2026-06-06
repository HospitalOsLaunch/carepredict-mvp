"""Retraining job definition."""

from __future__ import annotations

from dagster import AssetSelection, define_asset_job


retraining_pipeline = define_asset_job(
    name="retraining_pipeline",
    selection=AssetSelection.groups("ml", "monitoring", "serving"),
)
