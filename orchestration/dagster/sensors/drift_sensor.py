"""Drift sensor that triggers retraining when production MAE degrades."""

from __future__ import annotations

import json
from pathlib import Path

from dagster import RunRequest, SensorEvaluationContext, SkipReason, sensor
from jobs.retraining_pipeline import retraining_pipeline

DRIFT_REPORT_PATH = Path("reports/evidently/drift_metrics.json")
MAE_7D_THRESHOLD = 1.0


@sensor(job=retraining_pipeline, minimum_interval_seconds=24 * 60 * 60)
def drift_sensor(context: SensorEvaluationContext) -> RunRequest | SkipReason:
    """Trigger retraining when MAE over a 7-day rolling window exceeds 1.0."""
    if not DRIFT_REPORT_PATH.exists():
        return SkipReason("No Evidently drift report available")

    payload = json.loads(DRIFT_REPORT_PATH.read_text(encoding="utf-8"))
    mae_7d = float(payload.get("mae_7d", 0.0))
    if mae_7d <= MAE_7D_THRESHOLD:
        return SkipReason(f"MAE 7d within threshold: {mae_7d:.3f}")

    return RunRequest(
        run_key=f"drift-retraining-{context.cursor or 'initial'}-{mae_7d:.3f}",
        tags={
            "trigger": "drift",
            "mae_7d": f"{mae_7d:.3f}",
            "promotion_mode": "shadow",
        },
    )
