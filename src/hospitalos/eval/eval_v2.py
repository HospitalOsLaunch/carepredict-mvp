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
from hospitalos.dynamics.jepa_rssm import JepaRSSM, RSSMConfig, calendar_encoding, symexp
from hospitalos.encoders.ts_jepa.encoder import TransformerEncoder
from hospitalos.encoders.ts_jepa.patcher import Patchifier
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
    build_calendar_features,
    infer_transformer_depth,
    split_train_calibration_indices,
)

DEFAULT_ARTIFACT_DIR = Path("artifacts/v2_forecast")
DEFAULT_OUT = DEFAULT_ARTIFACT_DIR / "eval_v2.json"
BASELINE_PATH = Path("artifacts/baseline_v1_full.json")
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


@dataclass(frozen=True)
class V2Artifacts:
    """Loaded v2 forecast artifacts."""

    model: JepaRSSM
    train_config: dict[str, Any]
    q90_lo: np.ndarray
    q90_hi: np.ndarray
    artifact_paths: dict[str, Path]


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


def load_v2_artifacts(artifact_dir: Path) -> V2Artifacts:
    """Load v2 checkpoint, conformal quantiles, and train config."""
    checkpoint_path = artifact_dir / "checkpoint.pt"
    conformal_path = artifact_dir / "conformal_q.npz"
    config_path = artifact_dir / "train_config.json"
    checkpoint: dict[str, Any] = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    train_config = json.loads(config_path.read_text(encoding="utf-8"))
    q = np.load(conformal_path)
    q90_lo = np.asarray(q["q90_lo"], dtype=np.float64)
    q90_hi = np.asarray(q["q90_hi"], dtype=np.float64)
    cfg = RSSMConfig(**checkpoint["rssm_config"])
    patcher_state = checkpoint["patcher_state_dict"]
    encoder_state = checkpoint["context_encoder_state_dict"]
    patch_weight = patcher_state["proj.weight"]
    emb_dim = int(patch_weight.shape[0])
    patch_input_dim = int(patch_weight.shape[1])
    patch_len = int(train_config["encoder"]["patch_len"])
    if patch_len <= 0 or patch_input_dim % patch_len != 0:
        raise ValueError("invalid patch length in v2 artifacts")
    in_channels = patch_input_dim // patch_len
    patcher = Patchifier(in_channels=in_channels, patch_len=patch_len, emb_dim=emb_dim)
    encoder = TransformerEncoder(emb_dim=emb_dim, depth=infer_transformer_depth(encoder_state))
    patcher.load_state_dict(patcher_state)
    encoder.load_state_dict(encoder_state)
    model = JepaRSSM(cfg, encoder, patcher)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    return V2Artifacts(
        model=model,
        train_config=train_config,
        q90_lo=q90_lo,
        q90_hi=q90_hi,
        artifact_paths={
            "checkpoint": checkpoint_path,
            "conformal_q": conformal_path,
            "train_config": config_path,
        },
    )


def validate_critical_checks(
    *,
    artifacts: V2Artifacts,
    expected_git_hash: str | None = None,
) -> None:
    """Validate critical artifact assumptions before evaluation."""
    patch_len = int(artifacts.train_config["encoder"]["patch_len"])
    if patch_len not in {1, 24}:
        raise ValueError(f"expected encoder patch_len in {{1, 24}}, got {patch_len}")
    git_hash = str(artifacts.train_config["git_hash"])
    if expected_git_hash is not None and git_hash != expected_git_hash:
        raise ValueError("train_config git_hash does not match expected commit")
    if artifacts.q90_lo.shape != (48,) or artifacts.q90_hi.shape != (48,):
        raise ValueError("conformal q90 arrays must both have shape (48,)")


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
    )
    calibration = calibration_diagnostics(artifacts)
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
) -> list[V2Record]:
    """Collect h24 and h48 forecast records from v2 direct forecast outputs."""
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
        history = history_frame(feature_rows, origin=history_origin, length=168)
        if history is None:
            continue
        forecast = predict_from_history(artifacts.model, history, origin)
        for horizon in DEFAULT_HORIZONS:
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


def history_window_origin(artifacts: V2Artifacts, origin: datetime) -> datetime:
    """Return the timestamp that should end the feature history window."""
    if int(artifacts.train_config["encoder"]["patch_len"]) == 24:
        return origin - timedelta(hours=1)
    return origin


@torch.inference_mode()
def predict_from_history(model: JepaRSSM, history: Tensor, origin: datetime) -> Tensor:
    """Return a 48h raw-space direct forecast for the requested origin."""
    z = model.encode_series(history)
    states = model.unroll(z)
    origin_features = states["features"][:, -1:, :]
    if model.forecast_head[0].in_features == origin_features.shape[-1] + 2:
        day = torch.tensor([float(origin.weekday())], dtype=torch.float32)
        hour = torch.zeros(1, dtype=torch.float32)
        origin_calendar = calendar_encoding(hour, day)[:, -2:].reshape(1, 1, 2)
    else:
        calendar = build_calendar_features(origin - timedelta(hours=167), 168).unsqueeze(0)
        origin_calendar = calendar[:, -1:, :]
    forecast_input = torch.cat([origin_features, origin_calendar], dim=-1)
    forecast = symexp(model.forecast_head(forecast_input))
    return forecast[0, 0, :].detach().cpu()


def calibration_diagnostics(artifacts: V2Artifacts) -> dict[str, Any]:
    """Recompute calibration-set residual diagnostics without changing artifacts."""
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
    for batch in loader:
        pred = forecaster.predict_window(batch).numpy()
        truth = batch["siips"].numpy()
        origin_start = artifacts.model.cfg.forecast_horizon
        for origin_offset in range(pred.shape[1]):
            origin = origin_start + origin_offset
            for step in range(artifacts.model.cfg.forecast_horizon):
                for batch_index in range(truth.shape[0]):
                    target = float(truth[batch_index, origin + step + 1])
                    predicted = float(pred[batch_index, origin_offset, step])
                    residuals[step].append(target - predicted)
    counts = [len(values) for values in residuals]
    selected = {
        str(step): {
            "n_residuals": counts[step - 1],
            "mean_residual_y_true_minus_pred": safe_mean(np.asarray(residuals[step - 1])),
        }
        for step in (1, 24, 48)
    }
    return {
        "source": "recomputed_from_calibration_split_artifact_alignment",
        "n_per_horizon": counts[0] if len(set(counts)) == 1 else counts,
        "selected_horizons": selected,
    }


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
    """Print v2-daily vs v2-hourly and frozen floors side by side."""
    hourly = load_hourly_eval_summary()
    print(
        "horizon | model | mae | mae_ci_95 | coverage_90 | mean_interval_width"
    )
    for horizon in ("24", "48"):
        daily = result["metrics"]["horizons"][horizon]
        print_metric_row(horizon, "v2-daily", daily)
        if hourly is not None:
            print_metric_row(horizon, "v2-hourly", hourly["metrics"]["horizons"][horizon])
        floors = result["comparison"]["frozen_floors"][horizon]
        print_floor_row(horizon, "seasonal naive", floors["seasonal_naive_mae"])
        print_floor_row(horizon, "constant mean", floors["constant_mean_mae"])


def load_hourly_eval_summary() -> dict[str, Any] | None:
    """Load the previously generated hourly v2 evaluation JSON when available."""
    path = Path("artifacts/v2_forecast/eval_v2.json")
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


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
