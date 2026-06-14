"""Evaluate v2 direct forecast artifacts on the frozen temporal protocol."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import Tensor
from torch.utils.data import DataLoader

from hospitalos.data.timescale_adapter import (
    CHANNEL_NAMES,
    TimescaleDatasetConfig,
    TimescaleHospitalDataset,
)
from hospitalos.dynamics.jepa_rssm import forecast_origin_slice
from hospitalos.eval.baseline_v1 import (
    DEFAULT_HORIZONS,
    PRIMARY_SCOPE,
    CareLoadPoint,
    bootstrap_mae_ci,
    fetch_care_load_points,
    parse_utc,
    rmse,
    safe_mean,
    sha256_file,
)
from hospitalos.training.train_v2_forecast import (
    CalendarWindowDataset,
    FrozenForecastModel,
    split_train_calibration_indices,
)
from services.ml.forecasting.v2_forecast import (
    V2ForecastArtifacts as V2Artifacts,
)
from services.ml.forecasting.v2_forecast import (
    history_window_origin,
    load_v2_forecast_artifacts,
    predict_v2_from_history,
    v2_forecast_history_length,
    validate_v2_forecast_artifacts,
)

DEFAULT_ARTIFACT_DIR = Path("artifacts/v2_forecast")
DEFAULT_OUT = DEFAULT_ARTIFACT_DIR / "eval_v2.json"
BASELINE_PATH = Path("artifacts/baseline_v1_full.json")
DIAGNOSTIC_HORIZONS = (1, 24, 48)

FROZEN_FLOORS = {
    "24": {
        "seasonal_naive_mae": 197.96406593406593,
        "constant_mean_mae": 195.3278381751785,
        "v1_weekly_action_mae": 240.56707846978128,
    },
    "48": {
        "seasonal_naive_mae": 197.14430939226517,
        "constant_mean_mae": 194.7184092866583,
        "v1_weekly_action_mae": 251.4392921759718,
    },
}


@dataclass(frozen=True)
class V2Record:
    """One v2 forecast record for a frozen-protocol origin and horizon."""

    origin: datetime
    horizon: int
    y_true: float
    y_pred: float
    lower: float
    upper: float


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse v2 evaluation CLI arguments."""
    parser = argparse.ArgumentParser(description="Evaluate v2 direct forecast model.")
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--train-end", type=str, default="2025-07-01")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--stride-hours", type=int, default=24)
    parser.add_argument("--service", type=str, default=PRIMARY_SCOPE)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    """Run read-only v2 evaluation and persist JSON output."""
    args = parse_args(argv)
    train_end = parse_utc(str(args.train_end))
    artifacts = load_v2_artifacts(Path(args.artifact_dir))
    validate_critical_checks(artifacts=artifacts)
    points = fetch_care_load_points(service_ids=[str(args.service)])
    result = evaluate_v2(
        artifacts=artifacts,
        points=points,
        train_end=train_end,
        seed=int(args.seed),
        stride_hours=int(args.stride_hours),
        service_id=str(args.service),
    )
    write_json(result, Path(args.out))
    print_table(result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return result


load_v2_artifacts = load_v2_forecast_artifacts
validate_critical_checks = validate_v2_forecast_artifacts


def evaluate_v2(
    *,
    artifacts: V2Artifacts,
    points: list[CareLoadPoint],
    train_end: datetime,
    seed: int,
    stride_hours: int,
    service_id: str,
) -> dict[str, Any]:
    """Evaluate v2 forecasts on the frozen temporal protocol."""
    service_points = sorted(
        [point for point in points if point.service_id == service_id],
        key=lambda p: p.measured_at,
    )
    feature_rows = fetch_feature_rows(service_id=service_id, train_end=train_end)
    records = collect_v2_records(
        artifacts=artifacts,
        points=service_points,
        feature_rows=feature_rows,
        train_end=train_end,
        stride_hours=stride_hours,
        horizons=DIAGNOSTIC_HORIZONS,
    )
    calibration = calibration_diagnostics(artifacts)
    test_diagnostics = test_residual_diagnostics(records, calibration=calibration)
    horizons = {
        str(horizon): metric_block(
            [record for record in records if record.horizon == horizon],
            seed=seed,
        )
        for horizon in DEFAULT_HORIZONS
    }
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    n_skipped = skipped_window_count(
        points=service_points,
        train_end=train_end,
        stride_hours=stride_hours,
        records=records,
    )
    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "protocol": {
            "train_end": train_end.isoformat(),
            "origin_stride_hours": int(stride_hours),
            "primary_scope": service_id,
            "horizons": list(DEFAULT_HORIZONS),
            "raw_siips_space": True,
            "interval_formula": "lower = prediction - q90_lo[h]; upper = prediction + q90_hi[h]",
        },
        "critical_checks": {
            "encoder_patch_len": int(artifacts.train_config["encoder"]["patch_len"]),
            "train_config_git_hash": str(artifacts.train_config["git_hash"]),
            "conformal_q90_lo_shape": list(artifacts.q90_lo.shape),
            "conformal_q90_hi_shape": list(artifacts.q90_hi.shape),
            "test_windows_start_strictly_after_training_calibration": True,
        },
        "artifacts": {name: str(path) for name, path in artifacts.artifact_paths.items()},
        "model_artifact_sha256": {
            name: sha256_file(path) for name, path in artifacts.artifact_paths.items()
        },
        "train_config": artifacts.train_config,
        "metrics": {
            "horizons": horizons,
            "summary": summary_metrics(horizons, records=records, n_skipped=n_skipped),
            "n_test_windows": unique_origin_count(records),
            "n_services": 1,
            "n_skipped_windows": n_skipped,
            "calibration_n_per_horizon": calibration["n_per_horizon"],
            "coverage_noisy": True,
        },
        "calibration_diagnostics": calibration,
        "test_diagnostics": test_diagnostics,
        "comparison": {
            "baseline_v1_full": baseline["horizons"],
            "frozen_floors": FROZEN_FLOORS,
        },
    }


def collect_v2_records(
    *,
    artifacts: V2Artifacts,
    points: list[CareLoadPoint],
    feature_rows: dict[datetime, np.ndarray],
    train_end: datetime,
    stride_hours: int,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> list[V2Record]:
    """Collect forecast records from v2 direct forecast outputs."""
    by_time = {point.measured_at: point for point in points}
    origins = [
        point.measured_at
        for point in points
        if point.measured_at > train_end
        and point.measured_at.hour == 0
        and int((point.measured_at - train_end).total_seconds() // 3600) % stride_hours == 0
        and point.siips > 0.0
    ]
    records: list[V2Record] = []
    for origin in origins:
        history_origin = history_window_origin(artifacts, origin)
        history = history_frame(
            feature_rows,
            origin=history_origin,
            length=eval_history_length(artifacts),
        )
        if history is None:
            continue
        forecast = predict_from_history(artifacts.model, history, origin)
        for horizon in horizons:
            target = by_time.get(origin + timedelta(hours=horizon))
            if target is None or target.siips <= 0.0:
                continue
            pred = float(forecast[horizon - 1])
            lower = pred - float(artifacts.q90_lo[horizon - 1])
            upper = pred + float(artifacts.q90_hi[horizon - 1])
            records.append(
                V2Record(
                    origin=origin,
                    horizon=horizon,
                    y_true=float(target.siips),
                    y_pred=pred,
                    lower=lower,
                    upper=upper,
                )
            )
    return records


def fetch_feature_rows(*, service_id: str, train_end: datetime) -> dict[datetime, np.ndarray]:
    """Fetch canonical feature rows using the Timescale adapter code path read-only."""
    adapter = TimescaleHospitalDataset(
        TimescaleDatasetConfig(split="val", train_end=train_end.isoformat(), services=[service_id])
    )
    rows = adapter._fetch_rows()  # noqa: SLF001 - diagnostic/eval reuse of adapter SQL path.
    features: dict[datetime, np.ndarray] = {}
    for row in rows:
        if row["service_id"] != service_id:
            continue
        vector = np.asarray([float(row[name]) for name in CHANNEL_NAMES], dtype=np.float32)
        if np.isfinite(vector).all():
            features[row["measured_at"]] = vector
    return features


def history_frame(
    feature_rows: dict[datetime, np.ndarray],
    *,
    origin: datetime,
    length: int,
) -> Tensor | None:
    """Return the raw 7-channel feature history window ending at origin, or None."""
    values: list[np.ndarray] = []
    start = origin - timedelta(hours=length - 1)
    for offset in range(length):
        value = feature_rows.get(start + timedelta(hours=offset))
        if value is None:
            return None
        values.append(value)
    return torch.tensor(np.stack(values, axis=0), dtype=torch.float32).reshape(1, length, -1)


eval_history_length = v2_forecast_history_length
predict_from_history = predict_v2_from_history


def calibration_diagnostics(artifacts: V2Artifacts) -> dict[str, Any]:
    """Return calibration residual diagnostics from saved artifacts when available."""
    q = np.load(artifacts.artifact_paths["conformal_q"])
    if "residual_mean" in q and "n_residuals" in q:
        residual_mean = np.asarray(q["residual_mean"], dtype=np.float64)
        n_residuals = np.asarray(q["n_residuals"], dtype=np.int64)
        return {
            "source": "saved_conformal_residual_metadata",
            "n_per_horizon": int(n_residuals[0])
            if len(set(n_residuals.tolist())) == 1
            else n_residuals.tolist(),
            "selected_horizons": selected_residual_horizons(residual_mean, n_residuals),
        }
    return recompute_calibration_diagnostics(artifacts)


def recompute_calibration_diagnostics(artifacts: V2Artifacts) -> dict[str, Any]:
    """Recompute calibration residual diagnostics for legacy artifacts."""
    train_cfg = artifacts.train_config
    train_base = TimescaleHospitalDataset(
        TimescaleDatasetConfig(
            split="train",
            train_end=str(train_cfg["args"]["train_end"]),
            services=list(train_cfg["dataset"]["services"]),
        )
    )
    _, calibration_indices = split_train_calibration_indices(
        train_base.window_starts,
        cal_frac=float(train_cfg["dataset"]["calibration_frac"]),
    )
    dataset = CalendarWindowDataset(train_base, calibration_indices)
    loader = DataLoader(dataset, batch_size=8, shuffle=False, num_workers=0)
    residuals: list[list[float]] = [[] for _ in range(48)]
    forecaster = FrozenForecastModel(artifacts.model.eval())
    patch_len = int(artifacts.model.patcher.patch_len)
    for batch in loader:
        pred = forecaster.predict_window(batch).numpy()
        truth = batch["siips"].numpy()
        origin_slice = forecast_origin_slice(
            steps=int(truth.shape[1] // patch_len),
            patch_len=patch_len,
            forecast_horizon=int(artifacts.model.cfg.forecast_horizon),
        )
        for origin_offset in range(pred.shape[1]):
            origin = origin_slice.start + origin_offset
            target_start = (origin + 1) * patch_len
            for step in range(artifacts.model.cfg.forecast_horizon):
                for batch_index in range(truth.shape[0]):
                    target = float(truth[batch_index, target_start + step])
                    predicted = float(pred[batch_index, origin_offset, step])
                    residuals[step].append(target - predicted)
    counts = np.asarray([len(values) for values in residuals], dtype=np.int64)
    means = np.asarray([safe_mean(np.asarray(values)) for values in residuals], dtype=np.float64)
    return {
        "source": "recomputed_from_calibration_split_artifact_alignment",
        "n_per_horizon": int(counts[0]) if len(set(counts.tolist())) == 1 else counts.tolist(),
        "selected_horizons": selected_residual_horizons(means, counts),
    }


def selected_residual_horizons(means: np.ndarray, counts: np.ndarray) -> dict[str, Any]:
    """Return h1/h24/h48 residual diagnostic payload."""
    return {
        str(step): {
            "n_residuals": int(counts[step - 1]),
            "mean_residual_y_true_minus_pred": float(means[step - 1]),
        }
        for step in DIAGNOSTIC_HORIZONS
    }


def test_residual_diagnostics(
    records: list[V2Record],
    *,
    calibration: dict[str, Any],
) -> dict[str, Any]:
    """Compare test-set residual bias and early/late test MAE."""
    mean_residuals = {}
    for horizon in DIAGNOSTIC_HORIZONS:
        subset = [record for record in records if record.horizon == horizon]
        residuals = np.asarray(
            [record.y_true - record.y_pred for record in subset],
            dtype=np.float64,
        )
        mean_residuals[str(horizon)] = {
            "n_samples": int(len(subset)),
            "test_mean_residual_y_true_minus_pred": safe_mean(residuals),
            "calibration_mean_residual_y_true_minus_pred": calibration["selected_horizons"][
                str(horizon)
            ]["mean_residual_y_true_minus_pred"],
        }
    return {
        "selected_horizons": mean_residuals,
        "first_8_test_weeks_vs_last_8_test_weeks": first_last_eight_week_mae(records),
    }


def first_last_eight_week_mae(records: list[V2Record]) -> dict[str, Any]:
    """Return MAE on first and last eight evaluated test weeks for h24/h48."""
    origins = sorted({record.origin for record in records})
    first = set(origins[: 8 * 7])
    last = set(origins[-8 * 7 :])
    payload: dict[str, Any] = {}
    for horizon in DEFAULT_HORIZONS:
        first_errors = np.asarray(
            [
                abs(record.y_true - record.y_pred)
                for record in records
                if record.horizon == horizon and record.origin in first
            ],
            dtype=np.float64,
        )
        last_errors = np.asarray(
            [
                abs(record.y_true - record.y_pred)
                for record in records
                if record.horizon == horizon and record.origin in last
            ],
            dtype=np.float64,
        )
        payload[str(horizon)] = {
            "first_8_weeks_mae": safe_mean(first_errors),
            "first_8_weeks_n": int(len(first_errors)),
            "last_8_weeks_mae": safe_mean(last_errors),
            "last_8_weeks_n": int(len(last_errors)),
        }
    return payload


def metric_block(records: list[V2Record], *, seed: int) -> dict[str, Any]:
    """Compute frozen-protocol metrics for v2 records."""
    truth = np.asarray([record.y_true for record in records], dtype=np.float64)
    pred = np.asarray([record.y_pred for record in records], dtype=np.float64)
    lower = np.asarray([record.lower for record in records], dtype=np.float64)
    upper = np.asarray([record.upper for record in records], dtype=np.float64)
    errors = np.abs(truth - pred)
    return {
        "mae": safe_mean(errors),
        "rmse": rmse(truth, pred),
        "coverage90": safe_mean((truth >= lower) & (truth <= upper)),
        "mean_interval_width": safe_mean(upper - lower),
        "n_samples": int(len(records)),
        "mae_ci_95": bootstrap_mae_ci(errors, seed=seed),
    }


def summary_metrics(
    horizons: dict[str, dict[str, Any]],
    *,
    records: list[V2Record],
    n_skipped: int,
) -> dict[str, Any]:
    """Return acceptance-facing metric aliases for the v2 JSON."""
    return {
        "MAE@24h": horizons["24"]["mae"],
        "MAE@48h": horizons["48"]["mae"],
        "coverage90@24h": horizons["24"]["coverage90"],
        "coverage90@48h": horizons["48"]["coverage90"],
        "mean_interval_width@24h": horizons["24"]["mean_interval_width"],
        "mean_interval_width@48h": horizons["48"]["mean_interval_width"],
        "n_test_windows": unique_origin_count(records),
        "n_services": 1,
        "n_skipped_windows": int(n_skipped),
    }


def unique_origin_count(records: list[V2Record]) -> int:
    """Return unique evaluated origins across all horizons."""
    return len({record.origin for record in records})


def skipped_window_count(
    *,
    points: list[CareLoadPoint],
    train_end: datetime,
    stride_hours: int,
    records: list[V2Record],
) -> int:
    """Return count of daily origins skipped by history/target filters."""
    candidate_origins = {
        point.measured_at
        for point in points
        if point.measured_at > train_end
        and point.measured_at.hour == 0
        and int((point.measured_at - train_end).total_seconds() // 3600) % stride_hours == 0
        and point.siips > 0.0
    }
    evaluated = {record.origin for record in records}
    return max(len(candidate_origins - evaluated), 0)


def write_json(result: dict[str, Any], out_path: Path) -> None:
    """Write evaluation JSON."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def print_table(result: dict[str, Any]) -> None:
    """Print selected v2 variants and frozen floors side by side."""
    daily_500 = load_eval_summary(Path("artifacts/v2_forecast_daily/eval_v2.json"))
    hourly = load_eval_summary(Path("artifacts/v2_forecast/eval_v2.json"))
    current_label = artifact_dir_label(result)
    print("horizon | model | mae | mae_ci_95 | coverage_90 | mean_interval_width")
    for horizon in ("24", "48"):
        print_metric_row(horizon, current_label, result["metrics"]["horizons"][horizon])
        if daily_500 is not None:
            print_metric_row(horizon, "v2-daily-500", daily_500["metrics"]["horizons"][horizon])
        if hourly is not None:
            print_metric_row(horizon, "v2-hourly", hourly["metrics"]["horizons"][horizon])
        floors = result["comparison"]["frozen_floors"][horizon]
        print_floor_row(horizon, "seasonal naive", floors["seasonal_naive_mae"])
        print_floor_row(horizon, "constant mean", floors["constant_mean_mae"])


def load_eval_summary(path: Path) -> dict[str, Any] | None:
    """Load a previously generated v2 evaluation JSON when available."""
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def artifact_dir_label(result: dict[str, Any]) -> str:
    """Return a compact model label derived from the evaluated artifact directory."""
    checkpoint_path = Path(str(result["artifacts"]["checkpoint"]))
    name = checkpoint_path.parent.name
    if name.startswith("v2_forecast_"):
        return "v2-" + name.removeprefix("v2_forecast_").replace("_", "-")
    return name.replace("_", "-")


def print_metric_row(horizon: str, label: str, metrics: dict[str, Any]) -> None:
    """Print one model metric row."""
    ci = metrics["mae_ci_95"]
    print(
        f"{horizon:>7} | {label:<14} | {metrics['mae']:.2f} | "
        f"[{ci[0]:.2f}, {ci[1]:.2f}] | {metrics['coverage90']:.3f} | "
        f"{metrics['mean_interval_width']:.2f}"
    )


def print_floor_row(horizon: str, label: str, mae: float) -> None:
    """Print one floor row where interval metrics do not apply."""
    print(f"{horizon:>7} | {label:<14} | {mae:.2f} | n/a | n/a | n/a")


if __name__ == "__main__":
    main()
