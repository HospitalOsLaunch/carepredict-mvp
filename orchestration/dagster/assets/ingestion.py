"""Dagster ingestion assets."""

from __future__ import annotations

from dagster import AssetExecutionContext, asset


@asset(group_name="ingestion")
def hl7v2_raw_ingestion(context: AssetExecutionContext) -> str:
    """Placeholder asset for HL7v2 raw ingestion."""
    context.log.info("HL7v2 ingestion asset scaffolded")
    return "sih.raw"


@asset(group_name="ingestion")
def fhir_raw_ingestion(context: AssetExecutionContext) -> str:
    """Placeholder asset for FHIR raw ingestion."""
    context.log.info("FHIR ingestion asset scaffolded")
    return "fhir.raw"


@asset(group_name="ingestion")
def csv_raw_ingestion(context: AssetExecutionContext) -> str:
    """Placeholder asset for CSV raw ingestion."""
    context.log.info("CSV ingestion asset scaffolded")
    return "csv.raw"
