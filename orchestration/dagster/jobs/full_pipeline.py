"""Full pass 1 pipeline job."""

from __future__ import annotations

from dagster import AssetSelection, define_asset_job

full_pipeline = define_asset_job(
    name="full_pipeline",
    selection=AssetSelection.groups("ingestion", "normalization", "features"),
)
