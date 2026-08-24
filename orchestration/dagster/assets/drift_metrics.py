"""Dagster assets for drift metrics."""

from __future__ import annotations

import json
from pathlib import Path

from dagster import AssetExecutionContext, asset


@asset(group_name="monitoring")
def evidently_drift_report(context: AssetExecutionContext) -> dict[str, float]:
    """Read or initialize Evidently-style drift metrics."""
    report_path = Path("reports/evidently/drift_metrics.json")
    if not report_path.exists():
        context.log.info("No drift report found; returning nominal metrics")
        return {"mae_7d": 0.0}
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    mae_7d = float(payload.get("mae_7d", 0.0))
    context.log.info(f"Loaded drift metrics: mae_7d={mae_7d}")
    return {"mae_7d": mae_7d}
