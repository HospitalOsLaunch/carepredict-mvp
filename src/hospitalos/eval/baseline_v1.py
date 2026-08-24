"""Evaluate the frozen v1 RSSM baseline on canonical TimescaleDB SIIPS."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from data.synthetic.siips_generator import db_config_from_env
from services.ml.world_model.config import ServingConfig
from services.ml.world_model.inference import WorldModelService

PRIMARY_SCOPE = "urg-001"
DEFAULT_HORIZONS = (24, 48)
DEFAULT_ARTIFACTS = {
    "checkpoint": Path("artifacts/rssm_checkpoint.pt"),
    "scaler": Path("artifacts/siips_scaler.npz"),
    "conformal_residuals": Path("artifacts/conformal_residuals.npz"),
}


class Simulates(Protocol):
    """Protocol for v1-compatible simulation services."""

    model_version: str

    def simulate(
        self,
        history_siips: list[float],
        action_sequence: list[list[float]],
    ) -> list[dict[str, float | int | bool]]:
        """Return a v1 simulation response for the requested future actions."""


@dataclass(frozen=True)
class CareLoadPoint:
    """One hourly canonical SIIPS observation."""

    service_id: str
    measured_at: datetime
    siips: float


@dataclass(frozen=True)
class ForecastRecord:
    """One evaluated origin/horizon forecast."""

    origin: datetime
    horizon: int
    y_true: float
    y_pred: float
    lower: float
    upper: float
    seasonal_naive: float


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for frozen v1 baseline evaluation."""
    parser = argparse.ArgumentParser(description="Evaluate frozen v1 RSSM baseline.")
    parser.add_argument("--train-end", type=str, default="2025-07-01")
    parser.add_argument("--out", type=Path, default=Path("artifacts/baseline_v1.json"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--stride-hours", type=int, default=24)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the baseline evaluation and write frozen JSON plus SHA256 sidecar."""
    args = parse_args(argv)
    train_end = parse_utc(args.train_end)
    service = WorldModelService.from_artifacts(
        ServingConfig(
            checkpoint_path=str(DEFAULT_ARTIFACTS["checkpoint"]),
            scaler_path=str(DEFAULT_ARTIFACTS["scaler"]),
            calibration_residuals_path=str(DEFAULT_ARTIFACTS["conformal_residuals"]),
        )
    )
    points = fetch_care_load_points(service_ids=[PRIMARY_SCOPE])
    result = evaluate_baseline(
        service=service,
        points=points,
        train_end=train_end,
        seed=int(args.seed),
        stride_hours=int(args.stride_hours),
        primary_scope=PRIMARY_SCOPE,
        artifact_paths=DEFAULT_ARTIFACTS,
    )
    write_frozen_result(result, Path(args.out))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def evaluate_baseline(
    *,
    service: Simulates,
    points: list[CareLoadPoint],
    train_end: datetime,
    seed: int,
    stride_hours: int,
    primary_scope: str,
    artifact_paths: dict[str, Path],
) -> dict[str, Any]:
    """Evaluate v1 open-loop forecasts and seasonal-naive floor."""
    service_points = sorted(
        [point for point in points if point.service_id == primary_scope],
        key=lambda point: point.measured_at,
    )
    records_by_horizon = {
        horizon: collect_forecast_records(
            service=service,
            points=service_points,
            train_end=train_end,
            horizon=horizon,
            stride_hours=stride_hours,
        )
        for horizon in DEFAULT_HORIZONS
    }
    horizons: dict[str, Any] = {}
    for horizon, records in records_by_horizon.items():
        horizons[str(horizon)] = {
            "model": metric_block(records, seed=seed),
            "seasonal_naive": seasonal_metric_block(records, seed=seed),
        }

    artifact_sha = {
        name: sha256_file(path)
        for name, path in sorted(artifact_paths.items(), key=lambda item: item[0])
    }
    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "provenance": "existing_clean_pre_train_end",
        "primary_scope": primary_scope,
        "train_end": train_end.isoformat(),
        "origin_stride_hours": int(stride_hours),
        "open_loop": True,
        "model_version": str(service.model_version),
        "artifact_paths": {name: str(path) for name, path in sorted(artifact_paths.items())},
        "model_artifact_sha256": artifact_sha,
        "horizons": horizons,
    }


def collect_forecast_records(
    *,
    service: Simulates,
    points: list[CareLoadPoint],
    train_end: datetime,
    horizon: int,
    stride_hours: int,
) -> list[ForecastRecord]:
    """Collect open-loop forecast records for one horizon."""
    by_time = {point.measured_at: point for point in points}
    origins = [
        point.measured_at
        for point in points
        if point.measured_at >= train_end
        and point.measured_at.hour == 0
        and int((point.measured_at - train_end).total_seconds() // 3600) % stride_hours == 0
        and point.siips > 0.0
    ]
    records: list[ForecastRecord] = []
    for origin in origins:
        target_time = origin + timedelta(hours=horizon)
        naive_time = target_time - timedelta(hours=168)
        target = by_time.get(target_time)
        naive = by_time.get(naive_time)
        if target is None or naive is None:
            continue
        if target.siips <= 0.0 or naive.siips <= 0.0:
            continue
        history = history_until(points, origin)
        if not history:
            continue
        action_sequence = zero_actions(horizon=horizon, action_dim=5)
        forecast = service.simulate(history, action_sequence)
        step = forecast[horizon - 1]
        records.append(
            ForecastRecord(
                origin=origin,
                horizon=horizon,
                y_true=float(target.siips),
                y_pred=float(step["predicted_siips"]),
                lower=float(step["lower_bound"]),
                upper=float(step["upper_bound"]),
                seasonal_naive=float(naive.siips),
            )
        )
    return records


def history_until(
    points: list[CareLoadPoint], origin: datetime, *, max_length: int = 720
) -> list[float]:
    """Return bounded SIIPS history using only observations at or before origin."""
    history = [
        float(point.siips)
        for point in sorted(points, key=lambda point: point.measured_at)
        if point.measured_at <= origin and point.siips >= 0.0
    ]
    return history[-max_length:]


def zero_actions(*, horizon: int, action_dim: int) -> list[list[float]]:
    """Return a deterministic zero future action sequence."""
    return [[0.0 for _ in range(action_dim)] for _ in range(horizon)]


def metric_block(records: list[ForecastRecord], *, seed: int) -> dict[str, Any]:
    """Compute model metrics for forecast records."""
    truth = np.asarray([record.y_true for record in records], dtype=np.float64)
    pred = np.asarray([record.y_pred for record in records], dtype=np.float64)
    lower = np.asarray([record.lower for record in records], dtype=np.float64)
    upper = np.asarray([record.upper for record in records], dtype=np.float64)
    errors = np.abs(truth - pred)
    return {
        "mae": safe_mean(errors),
        "rmse": rmse(truth, pred),
        "mapie_coverage_90": safe_mean((truth >= lower) & (truth <= upper)),
        "mean_interval_width": safe_mean(upper - lower),
        "n_samples": int(len(records)),
        "mae_ci_95": bootstrap_mae_ci(errors, seed=seed),
    }


def seasonal_metric_block(records: list[ForecastRecord], *, seed: int) -> dict[str, Any]:
    """Compute seasonal-naive floor metrics on the same origin/target pairs."""
    truth = np.asarray([record.y_true for record in records], dtype=np.float64)
    pred = np.asarray([record.seasonal_naive for record in records], dtype=np.float64)
    errors = np.abs(truth - pred)
    return {
        "mae": safe_mean(errors),
        "rmse": rmse(truth, pred),
        "n_samples": int(len(records)),
        "mae_ci_95": bootstrap_mae_ci(errors, seed=seed),
    }


def bootstrap_mae_ci(errors: np.ndarray, *, seed: int, n_bootstrap: int = 2000) -> list[float]:
    """Return seeded percentile bootstrap CI for MAE from absolute errors."""
    if errors.size == 0:
        return [float("nan"), float("nan")]
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, errors.size, size=(n_bootstrap, errors.size))
    samples = errors[indices].mean(axis=1)
    return [
        float(np.quantile(samples, 0.025)),
        float(np.quantile(samples, 0.975)),
    ]


def rmse(truth: np.ndarray, pred: np.ndarray) -> float:
    """Return RMSE, or NaN for empty arrays."""
    if truth.size == 0:
        return float("nan")
    return float(np.sqrt(np.mean(np.square(truth - pred))))


def safe_mean(values: np.ndarray) -> float:
    """Return float mean for numeric or boolean arrays, or NaN when empty."""
    if values.size == 0:
        return float("nan")
    return float(np.mean(values))


def write_frozen_result(result: dict[str, Any], out_path: Path) -> None:
    """Write baseline JSON and matching SHA256 sidecar."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    out_path.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
    out_path.with_suffix(".sha256").write_text(f"{digest}\n", encoding="utf-8")


def fetch_care_load_points(*, service_ids: list[str]) -> list[CareLoadPoint]:
    """Fetch canonical care_load SIIPS points with deterministic ordering."""
    config = db_config_from_env()
    psycopg2 = _psycopg2()
    with psycopg2.connect(**config) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
                SELECT service_id, measured_at, siips_score::DOUBLE PRECISION
                FROM canonical.care_load
                WHERE service_id = ANY(%s)
                ORDER BY service_id ASC, measured_at ASC
                """,
            (service_ids,),
        )
        rows = cursor.fetchall()
    return [
        CareLoadPoint(
            service_id=str(service_id),
            measured_at=to_utc(measured_at),
            siips=float(siips),
        )
        for service_id, measured_at, siips in rows
    ]


def sha256_file(path: Path) -> str:
    """Return SHA256 digest for a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_utc(value: str) -> datetime:
    """Parse an ISO date/datetime into an aware UTC datetime."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def to_utc(value: datetime) -> datetime:
    """Normalize database timestamps to aware UTC datetimes."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _psycopg2() -> Any:
    import psycopg2

    return psycopg2


if __name__ == "__main__":
    raise SystemExit(main())
