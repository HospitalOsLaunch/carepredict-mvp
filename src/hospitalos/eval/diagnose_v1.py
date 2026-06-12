"""Diagnostic-only probes for the frozen full-window v1 RSSM baseline."""

from __future__ import annotations

import argparse
import inspect
import json
from dataclasses import dataclass
from types import SimpleNamespace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import torch

from services.ml.world_model.config import ServingConfig
from services.ml.world_model.inference import WorldModelService
from services.ml.world_model.rssm import RSSMState
from hospitalos.eval.baseline_v1 import (
    CareLoadPoint,
    ForecastRecord,
    PRIMARY_SCOPE,
    collect_forecast_records,
    fetch_care_load_points,
    history_until,
    parse_utc,
    to_utc,
    zero_actions,
)
from data.synthetic.siips_generator import db_config_from_env
from scripts.train_rssm_synthetic import build_action_matrix

ARTIFACTS = {
    "checkpoint": Path("artifacts/v1_full/rssm_checkpoint.pt"),
    "scaler": Path("artifacts/v1_full/siips_scaler.npz"),
    "conformal_residuals": Path("artifacts/v1_full/conformal_residuals.npz"),
}
DEFAULT_TRAIN_END = "2025-07-01"
DEFAULT_STRIDE_HOURS = 24
DEFAULT_SEED = 42
DEFAULT_TRAJECTORY_COUNT = 5
DEFAULT_OUTPUT_DIR = Path("runs/diagnose_v1")
WEEKLY_LAG_HOURS = 168




@dataclass(frozen=True)
class ActionEvent:
    """Canonical event timestamp compatible with train_rssm_synthetic action derivation."""

    admission_time: datetime | None = None
    discharge_time: datetime | None = None

@dataclass(frozen=True)
class TargetRecord:
    """One diagnostic origin/target pair."""

    origin: datetime
    target_time: datetime
    y_true: float
    y_pred: float


@dataclass(frozen=True)
class ScalerTrace:
    """Scaler and model values for one open-loop forecast step."""

    origin: str
    raw_last_history_siips: float
    scaler_mean: float
    scaler_std: float
    scaled_last_history_siips: float
    normalized_model_output: float
    unscaled_prediction: float
    service_simulate_prediction: float


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the read-only diagnostic."""
    parser = argparse.ArgumentParser(description="Diagnose v1_full RSSM baseline behavior.")
    parser.add_argument("--train-end", type=str, default=DEFAULT_TRAIN_END)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--stride-hours", type=int, default=DEFAULT_STRIDE_HOURS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run all B0d diagnostics and print a JSON summary."""
    args = parse_args(argv)
    train_end = parse_utc(str(args.train_end))
    service = load_v1_full_service()
    points = fetch_care_load_points(service_ids=[PRIMARY_SCOPE])
    service_points = sorted(points, key=lambda point: point.measured_at)

    h24_records = collect_forecast_records(
        service=service,
        points=service_points,
        train_end=train_end,
        horizon=24,
        stride_hours=int(args.stride_hours),
    )
    h48_records = collect_forecast_records(
        service=service,
        points=service_points,
        train_end=train_end,
        horizon=48,
        stride_hours=int(args.stride_hours),
    )
    timestamps = [point.measured_at for point in service_points]
    canonical_events = fetch_canonical_action_events(service_id=PRIMARY_SCOPE)
    lagged_actions = build_action_matrix(canonical_events, timestamps, action_dim=service.rssm_config.action_dim)
    lagged_h24_records = collect_lagged_action_records(
        service=service,
        points=service_points,
        actions=lagged_actions,
        train_end=train_end,
        horizon=24,
        stride_hours=int(args.stride_hours),
    )
    lagged_h48_records = collect_lagged_action_records(
        service=service,
        points=service_points,
        actions=lagged_actions,
        train_end=train_end,
        horizon=48,
        stride_hours=int(args.stride_hours),
    )
    train_mean = train_window_mean(service_points=service_points, train_end=train_end)
    origin_targets_24 = target_records(h24_records)
    trajectory_path = write_trajectory_dump(
        service=service,
        points=service_points,
        records=h48_records,
        seed=int(args.seed),
        out_dir=Path(args.out_dir),
    )
    scaler_trace = scaler_sanity_trace(service=service, points=service_points, origin=h24_records[0].origin)

    report = {
        "scope": {
            "artifacts": {name: str(path) for name, path in ARTIFACTS.items()},
            "primary_scope": PRIMARY_SCOPE,
            "train_end": train_end.isoformat(),
            "origin_stride_hours": int(args.stride_hours),
        },
        "prediction_variance_h24": prediction_variance(origin_targets_24),
        "constant_mean_floor": {
            "train_window_mean_siips": train_mean,
            "h24": constant_mean_metrics(records=h24_records, train_mean=train_mean),
            "h48": constant_mean_metrics(records=h48_records, train_mean=train_mean),
            "reference_model_mae": {
                "h24": mae_from_records(h24_records),
                "h48": mae_from_records(h48_records),
            },
        },
        "weekly_lag_action_variant": {
            "description": "Future action_sequence uses canonical action vectors observed at the same hours one week earlier; history actions remain internal to WorldModelService.",
            "action_derivation_code_path": action_derivation_evidence(),
            "zero_action": {
                "h24": metric_summary(records=h24_records),
                "h48": metric_summary(records=h48_records),
            },
            "weekly_lag_actions": {
                "h24": metric_summary(records=lagged_h24_records),
                "h48": metric_summary(records=lagged_h48_records),
            },
        },
        "trajectory_dump": {
            "path": str(trajectory_path),
            "origin_count": DEFAULT_TRAJECTORY_COUNT,
            "horizon_hours": 48,
        },
        "action_feed_evidence": action_feed_evidence(),
        "scaler_sanity": scaler_trace.__dict__,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def load_v1_full_service() -> WorldModelService:
    """Load the v1_full service from its frozen artifacts."""
    return WorldModelService.from_artifacts(
        ServingConfig(
            checkpoint_path=str(ARTIFACTS["checkpoint"]),
            scaler_path=str(ARTIFACTS["scaler"]),
            calibration_residuals_path=str(ARTIFACTS["conformal_residuals"]),
        )
    )


def target_records(records: list[ForecastRecord]) -> list[TargetRecord]:
    """Convert baseline forecast records into compact target records."""
    return [
        TargetRecord(
            origin=record.origin,
            target_time=record.origin + timedelta(hours=record.horizon),
            y_true=float(record.y_true),
            y_pred=float(record.y_pred),
        )
        for record in records
    ]


def prediction_variance(records: list[TargetRecord]) -> dict[str, Any]:
    """Report predicted and true SIIPS variability for h+24 targets."""
    pred = np.asarray([record.y_pred for record in records], dtype=np.float64)
    truth = np.asarray([record.y_true for record in records], dtype=np.float64)
    ratio = float(np.std(pred) / np.std(truth)) if truth.size and np.std(truth) > 0.0 else float("nan")
    return {
        "n_origins": int(len(records)),
        "pred_std": float(np.std(pred)) if pred.size else float("nan"),
        "pred_min": float(np.min(pred)) if pred.size else float("nan"),
        "pred_max": float(np.max(pred)) if pred.size else float("nan"),
        "pred_range": float(np.max(pred) - np.min(pred)) if pred.size else float("nan"),
        "true_std": float(np.std(truth)) if truth.size else float("nan"),
        "true_min": float(np.min(truth)) if truth.size else float("nan"),
        "true_max": float(np.max(truth)) if truth.size else float("nan"),
        "true_range": float(np.max(truth) - np.min(truth)) if truth.size else float("nan"),
        "pred_std_to_true_std_ratio": ratio,
        "near_constant_flag_pred_std_lt_20pct_true_std": bool(np.isfinite(ratio) and ratio < 0.2),
    }



def fetch_canonical_action_events(*, service_id: str) -> SimpleNamespace:
    """Fetch canonical admissions/discharges and expose the training action API shape."""
    config = db_config_from_env()
    import psycopg2

    with psycopg2.connect(**config) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT admission_time
                FROM canonical.admissions
                WHERE service_id = %s
                ORDER BY admission_time ASC
                """,
                (service_id,),
            )
            admissions = [
                ActionEvent(admission_time=to_utc(admission_time))
                for (admission_time,) in cursor.fetchall()
            ]
            cursor.execute(
                """
                SELECT discharge_time
                FROM canonical.discharges
                WHERE service_id = %s
                ORDER BY discharge_time ASC
                """,
                (service_id,),
            )
            discharges = [
                ActionEvent(discharge_time=to_utc(discharge_time))
                for (discharge_time,) in cursor.fetchall()
            ]
    return SimpleNamespace(admissions=admissions, discharges=discharges)


def collect_lagged_action_records(
    *,
    service: WorldModelService,
    points: list[CareLoadPoint],
    actions: np.ndarray,
    train_end: datetime,
    horizon: int,
    stride_hours: int,
) -> list[ForecastRecord]:
    """Collect forecasts using future actions copied from the same hours one week earlier."""
    by_time = {point.measured_at: point for point in points}
    time_to_index = {point.measured_at: index for index, point in enumerate(points)}
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
        naive_time = target_time - timedelta(hours=WEEKLY_LAG_HOURS)
        target = by_time.get(target_time)
        naive = by_time.get(naive_time)
        if target is None or naive is None or target.siips <= 0.0 or naive.siips <= 0.0:
            continue
        action_sequence = lagged_action_sequence(
            origin=origin,
            horizon=horizon,
            actions=actions,
            time_to_index=time_to_index,
        )
        if action_sequence is None:
            continue
        history = history_until(points, origin)
        if not history:
            continue
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


def lagged_action_sequence(
    *,
    origin: datetime,
    horizon: int,
    actions: np.ndarray,
    time_to_index: dict[datetime, int],
) -> list[list[float]] | None:
    """Return action vectors from matching future hours shifted back by one week."""
    sequence: list[list[float]] = []
    for hour in range(1, horizon + 1):
        lagged_time = origin + timedelta(hours=hour - WEEKLY_LAG_HOURS)
        index = time_to_index.get(lagged_time)
        if index is None:
            return None
        sequence.append([float(value) for value in actions[index].tolist()])
    return sequence


def metric_summary(*, records: list[ForecastRecord]) -> dict[str, Any]:
    """Return MAE/RMSE and h-target prediction variance for diagnostic comparisons."""
    truth = np.asarray([record.y_true for record in records], dtype=np.float64)
    pred = np.asarray([record.y_pred for record in records], dtype=np.float64)
    errors = np.abs(truth - pred)
    pred_std = float(np.std(pred)) if pred.size else float("nan")
    true_std = float(np.std(truth)) if truth.size else float("nan")
    return {
        "mae": float(np.mean(errors)) if errors.size else float("nan"),
        "rmse": float(np.sqrt(np.mean(np.square(truth - pred)))) if truth.size else float("nan"),
        "n_samples": int(len(records)),
        "pred_std": pred_std,
        "true_std": true_std,
        "pred_std_to_true_std_ratio": pred_std / true_std if true_std > 0.0 else float("nan"),
    }


def action_derivation_evidence() -> dict[str, Any]:
    """Return source-line evidence for the imported training action builder."""
    source_lines, line_start = inspect.getsourcelines(build_action_matrix)
    return {
        "file": inspect.getsourcefile(build_action_matrix),
        "function": "build_action_matrix",
        "line_start": line_start,
        "relevant_lines": relevant_lines(
            source_lines,
            line_start,
            includes=(
                "The action order",
                "actions = np.zeros",
                "actions[index, 0]",
                "actions[index, 1]",
            ),
        ),
    }

def train_window_mean(*, service_points: list[CareLoadPoint], train_end: datetime) -> float:
    """Return the pre-train-end mean SIIPS, excluding non-positive artifacts."""
    values = [point.siips for point in service_points if point.measured_at < train_end and point.siips > 0.0]
    if not values:
        raise ValueError("No positive train-window SIIPS values found")
    return float(np.mean(np.asarray(values, dtype=np.float64)))


def constant_mean_metrics(*, records: list[ForecastRecord], train_mean: float) -> dict[str, float | int]:
    """Compute the constant train-mean MAE/RMSE on the same target pairs."""
    truth = np.asarray([record.y_true for record in records], dtype=np.float64)
    pred = np.full(shape=truth.shape, fill_value=float(train_mean), dtype=np.float64)
    errors = np.abs(truth - pred)
    rmse = float(np.sqrt(np.mean(np.square(truth - pred)))) if truth.size else float("nan")
    return {
        "mae": float(np.mean(errors)) if errors.size else float("nan"),
        "rmse": rmse,
        "n_samples": int(truth.size),
    }


def mae_from_records(records: list[ForecastRecord]) -> float:
    """Return model MAE from collected forecast records."""
    errors = [abs(record.y_true - record.y_pred) for record in records]
    return float(np.mean(np.asarray(errors, dtype=np.float64))) if errors else float("nan")


def write_trajectory_dump(
    *,
    service: WorldModelService,
    points: list[CareLoadPoint],
    records: list[ForecastRecord],
    seed: int,
    out_dir: Path,
) -> Path:
    """Write five fixed-seed 48h predicted-vs-true trajectories."""
    if len(records) < DEFAULT_TRAJECTORY_COUNT:
        raise ValueError("Not enough records to sample trajectory origins")
    rng = np.random.default_rng(seed)
    selected = sorted(rng.choice(len(records), size=DEFAULT_TRAJECTORY_COUNT, replace=False).tolist())
    by_time = {point.measured_at: point for point in points}
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "trajectories.txt"
    lines: list[str] = []
    for selected_index in selected:
        record = records[selected_index]
        history = history_until(points, record.origin)
        forecast = service.simulate(history, zero_actions(horizon=48, action_dim=5))
        lines.append(f"origin={record.origin.isoformat()} selected_index={selected_index}")
        lines.append("hour,predicted_siips,true_siips,error")
        for hour in range(1, 49):
            target_time = record.origin + timedelta(hours=hour)
            true_point = by_time.get(target_time)
            true_value = float(true_point.siips) if true_point is not None else float("nan")
            pred_value = float(forecast[hour - 1]["predicted_siips"])
            error = pred_value - true_value if np.isfinite(true_value) else float("nan")
            lines.append(f"{hour},{pred_value:.6f},{true_value:.6f},{error:.6f}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def action_feed_evidence() -> dict[str, Any]:
    """Return source-line evidence for historical and future action inputs."""
    simulate_func = inspect.unwrap(WorldModelService.simulate)
    simulate_start, simulate_line = inspect.getsourcelines(simulate_func)
    collect_start, collect_line = inspect.getsourcelines(collect_forecast_records)
    zero_start, zero_line = inspect.getsourcelines(zero_actions)
    return {
        "diagnosis": "Historical actions are zeros inside WorldModelService; future open-loop actions are the action_sequence argument. The baseline evaluator passes zero_actions(), so hours > origin t use all-zero action vectors.",
        "world_model_service_simulate": {
            "file": inspect.getsourcefile(simulate_func),
            "line_start": simulate_line,
            "relevant_lines": relevant_lines(
                simulate_start,
                simulate_line,
                includes=("history_actions = torch.zeros", "future_actions = torch.tensor", "imagine_step"),
            ),
        },
        "baseline_collect_forecast_records": {
            "file": inspect.getsourcefile(collect_forecast_records),
            "line_start": collect_line,
            "relevant_lines": relevant_lines(
                collect_start,
                collect_line,
                includes=("action_sequence = zero_actions", "forecast = service.simulate"),
            ),
        },
        "baseline_zero_actions": {
            "file": inspect.getsourcefile(zero_actions),
            "line_start": zero_line,
            "relevant_lines": relevant_lines(zero_start, zero_line, includes=("return [[0.0",)),
        },
    }


def relevant_lines(source_lines: list[str], line_start: int, *, includes: tuple[str, ...]) -> list[dict[str, str | int]]:
    """Extract source lines containing any requested snippet."""
    matches: list[dict[str, str | int]] = []
    for offset, line in enumerate(source_lines):
        if any(snippet in line for snippet in includes):
            matches.append({"line": line_start + offset, "code": line.rstrip()})
    return matches


def scaler_sanity_trace(*, service: WorldModelService, points: list[CareLoadPoint], origin: datetime) -> ScalerTrace:
    """Trace one origin through normalization, model decode and inverse scaling."""
    history = history_until(points, origin)
    if not history:
        raise ValueError("No history for scaler trace origin")
    dtype = next(service.model.parameters()).dtype
    history_array = np.asarray(history[-service.config.max_history_length :], dtype=np.float64)
    normalized_history = (history_array - service.scaler.mean) / service.scaler.std
    history_obs = torch.tensor(
        normalized_history.reshape(1, -1, service.rssm_config.obs_dim),
        device=service.device,
        dtype=dtype,
    )
    history_actions = torch.zeros(
        1,
        int(history_obs.shape[1]),
        service.rssm_config.action_dim,
        device=service.device,
        dtype=dtype,
    )
    with torch.inference_mode():
        states, _priors, _posteriors = service.model.observe_sequence(history_obs, history_actions)
        state: RSSMState = {"h": states["h"][-1], "z": states["z"][-1]}
        zero_action = torch.zeros(1, service.rssm_config.action_dim, device=service.device, dtype=dtype)
        state, _prior = service.model.imagine_step(state, zero_action)
        normalized_pred, _reward = service.model.decode(state)
    normalized_value = float(normalized_pred.reshape(-1)[0].detach().cpu().item())
    unscaled = normalized_value * service.scaler.std + service.scaler.mean
    simulate_prediction = float(service.simulate(history, zero_actions(horizon=1, action_dim=5))[0]["predicted_siips"])
    return ScalerTrace(
        origin=origin.isoformat(),
        raw_last_history_siips=float(history_array[-1]),
        scaler_mean=float(service.scaler.mean),
        scaler_std=float(service.scaler.std),
        scaled_last_history_siips=float(normalized_history[-1]),
        normalized_model_output=normalized_value,
        unscaled_prediction=float(unscaled),
        service_simulate_prediction=simulate_prediction,
    )


if __name__ == "__main__":
    raise SystemExit(main())
