"""Persistence of a run: one ``forecast_runs`` row and its ``forecast_values``."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import insert
from sqlalchemy.orm import Session

from services.admissions_smr.models import ForecastRun, ForecastValue
from services.forecast_engine.models import HORIZON
from services.forecast_engine.pipeline import RunResult


def save_run(session: Session, group_id: int, result: RunResult, now: datetime) -> ForecastRun:
    run = ForecastRun(
        group_id=group_id,
        created_at=now,
        as_of=result.as_of,
        model_version=result.model_version,
        horizon_days=HORIZON,
        status="ok",
        params_json=json.dumps(result.params, ensure_ascii=False, sort_keys=True),
        metrics_json=json.dumps(result.metrics, ensure_ascii=False, sort_keys=True),
    )
    session.add(run)
    session.flush()
    if result.values:
        session.execute(
            insert(ForecastValue),
            [{"run_id": run.id, **row.__dict__} for row in result.values],
        )
    session.commit()
    return run


def save_failure(
    session: Session, group_id: int, as_of: date, model_version: str, error: str, now: datetime
) -> ForecastRun:
    """A failed run is recorded too: the API keeps serving the last good one, and says so."""
    session.rollback()
    run = ForecastRun(
        group_id=group_id,
        created_at=now,
        as_of=as_of,
        model_version=model_version,
        horizon_days=HORIZON,
        status="failed",
        params_json="{}",
        metrics_json=json.dumps({"error": error[:2000]}, ensure_ascii=False),
    )
    session.add(run)
    session.commit()
    return run


def utcnow() -> datetime:
    return datetime.now(UTC)


def load_json(text: str) -> dict[str, Any]:
    value = json.loads(text or "{}")
    return value if isinstance(value, dict) else {}
