"""F5c diagnostics for daily v2 forecast state-index alignment."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import torch

from hospitalos.eval.baseline_v1 import (
    DEFAULT_HORIZONS,
    PRIMARY_SCOPE,
    CareLoadPoint,
    parse_utc,
    safe_mean,
)
from hospitalos.eval.eval_v2 import (
    V2Artifacts,
    V2Record,
    fetch_care_load_points,
    fetch_feature_rows,
    history_frame,
    history_window_origin,
    load_eval_summary,
    load_v2_artifacts,
    metric_block,
    predict_from_history,
    print_metric_row,
    skipped_window_count,
    unique_origin_count,
)

DEFAULT_TRAIN_END = "2025-07-01"
DEFAULT_SEED = 42
DEFAULT_STRIDE_HOURS = 24
DAILY_500_DIR = Path("artifacts/v2_forecast_daily")
DAILY_5K_DIR = Path("artifacts/v2_forecast_daily_5k")
MISALIGNED_DAILY_500_MAE = {"24": 217.17, "48": 206.68}
MISALIGNED_DAILY_5K_MAE = {"24": 244.31, "48": 280.20}


@dataclass(frozen=True)
class AlignedEvalResult:
    """Aligned frozen-protocol metrics for one checkpoint."""

    label: str
    artifact_dir: str
    history_hours: int
    extracted_state_index: int
    horizons: dict[str, dict[str, Any]]
    n_test_windows: int
    n_skipped_windows: int


def main() -> dict[str, Any]:
    """Run F5c read-only diagnostics and print a JSON report."""
    train_end = parse_utc(DEFAULT_TRAIN_END)
    points = fetch_care_load_points(service_ids=[PRIMARY_SCOPE])
    feature_rows = fetch_feature_rows(service_id=PRIMARY_SCOPE, train_end=train_end)

    daily_5k = load_v2_artifacts(DAILY_5K_DIR)
    daily_500 = load_v2_artifacts(DAILY_500_DIR)
    origin_evidence = origin_index_evidence()
    state_norms = state_norm_probe(
        artifacts=daily_5k,
        points=points,
        feature_rows=feature_rows,
        train_end=train_end,
        seed=DEFAULT_SEED,
    )
    aligned_500 = aligned_eval(
        label="v2-daily-500-aligned-d4",
        artifacts=daily_500,
        artifact_dir=DAILY_500_DIR,
        points=points,
        feature_rows=feature_rows,
        train_end=train_end,
        seed=DEFAULT_SEED,
    )
    aligned_5k = aligned_eval(
        label="v2-daily-5k-aligned-d4",
        artifacts=daily_5k,
        artifact_dir=DAILY_5K_DIR,
        points=points,
        feature_rows=feature_rows,
        train_end=train_end,
        seed=DEFAULT_SEED,
    )
    report = {
        "diagnostic": "F5c",
        "scope": {
            "service": PRIMARY_SCOPE,
            "train_end": DEFAULT_TRAIN_END,
            "stride_hours": DEFAULT_STRIDE_HOURS,
            "read_only": True,
            "retrained": False,
            "recalibrated": False,
        },
        "origin_index_evidence": origin_evidence,
        "state_norm_probe": state_norms,
        "aligned_re_eval": {
            "results": {
                aligned_5k.label: asdict(aligned_5k),
                aligned_500.label: asdict(aligned_500),
            },
            "misaligned_reference_mae": {
                "v2-daily-5k": MISALIGNED_DAILY_5K_MAE,
                "v2-daily-500": MISALIGNED_DAILY_500_MAE,
            },
        },
    }
    print_aligned_table(report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return report


def origin_index_evidence() -> dict[str, Any]:
    """Return file/line evidence for eval-time and train-time forecast origins."""
    return {
        "eval_time": {
            "history_window": {
                "file": "src/hospitalos/eval/eval_v2.py",
                "lines": [275, 276, 333, 334, 335, 336],
                "meaning": (
                    "Daily eval ends the 168h history at origin-1h, producing "
                    "7 daily tokens for a 7-day window."
                ),
            },
            "state_extraction": {
                "file": "src/hospitalos/eval/eval_v2.py",
                "lines": [343, 344, 345],
                "meaning": (
                    "predict_from_history uses states['features'][:, -1:, :], "
                    "so with 7 tokens it extracts d=6."
                ),
            },
        },
        "training_and_calibration": {
            "forecast_origin_slice": {
                "file": "src/hospitalos/dynamics/jepa_rssm.py",
                "lines": [292, 293, 294],
                "meaning": "For 7 daily states, slice(1, 5) gives trained origins d in {1,2,3,4}.",
            },
            "forecast_loss_targets": {
                "file": "src/hospitalos/dynamics/jepa_rssm.py",
                "lines": [240, 245, 246, 247, 248, 249, 250],
                "meaning": (
                    "Training loss iterates over that same origin range and targets the next 48h."
                ),
            },
            "calibration_targets": {
                "file": "src/hospitalos/training/train_v2_forecast.py",
                "lines": [452, 456, 457, 458, 459],
                "meaning": (
                    "Calibration uses origin_start=1 for daily patches, matching d in {1,2,3,4}."
                ),
            },
        },
        "match": False,
        "plain_statement": (
            "They do not match: default eval extracts d=6, while "
            "training/calibration supervise d in {1,2,3,4}."
        ),
    }


@torch.inference_mode()
def state_norm_probe(
    *,
    artifacts: V2Artifacts,
    points: list[CareLoadPoint],
    feature_rows: dict[datetime, np.ndarray],
    train_end: datetime,
    seed: int,
) -> dict[str, Any]:
    """Return mean L2 norms of h_d for d=0..6 over 20 fixed test windows."""
    origins = fixed_origins(
        points=points,
        train_end=train_end,
        feature_rows=feature_rows,
        limit=20,
        length=168,
    )
    torch.manual_seed(seed)
    h_norms: list[list[float]] = [[] for _ in range(7)]
    for origin in origins:
        history_origin = history_window_origin(artifacts, origin)
        history = history_frame(feature_rows, origin=history_origin, length=168)
        if history is None:
            continue
        z = artifacts.model.encode_series(history)
        states = artifacts.model.unroll(z)
        h = states["features"][:, :, : artifacts.model.cfg.deter]
        norms = torch.linalg.vector_norm(h[0], ord=2, dim=-1).detach().cpu().numpy()
        for index, value in enumerate(norms[:7]):
            h_norms[index].append(float(value))
    means = {
        f"d{index}": safe_mean(np.asarray(values, dtype=np.float64))
        for index, values in enumerate(h_norms)
    }
    return {
        "artifact_dir": str(DAILY_5K_DIR),
        "n_windows": len(origins),
        "history_hours": 168,
        "mean_l2_norm_h_d": means,
        "pattern": state_norm_pattern(means),
    }


def aligned_eval(
    *,
    label: str,
    artifacts: V2Artifacts,
    artifact_dir: Path,
    points: list[CareLoadPoint],
    feature_rows: dict[datetime, np.ndarray],
    train_end: datetime,
    seed: int,
) -> AlignedEvalResult:
    """Evaluate a daily checkpoint with exactly 5 days of history so last state is d=4."""
    records = collect_aligned_records(
        artifacts=artifacts,
        points=points,
        feature_rows=feature_rows,
        train_end=train_end,
        seed=seed,
        history_hours=120,
    )
    horizons: dict[str, dict[str, Any]] = {}
    for horizon in DEFAULT_HORIZONS:
        subset = [record for record in records if record.horizon == horizon]
        horizons[str(horizon)] = metric_block(subset, seed=seed)
    return AlignedEvalResult(
        label=label,
        artifact_dir=str(artifact_dir),
        history_hours=120,
        extracted_state_index=4,
        horizons=horizons,
        n_test_windows=unique_origin_count(records),
        n_skipped_windows=skipped_window_count(
            points=points,
            train_end=train_end,
            stride_hours=DEFAULT_STRIDE_HOURS,
            records=records,
        ),
    )


def collect_aligned_records(
    *,
    artifacts: V2Artifacts,
    points: list[CareLoadPoint],
    feature_rows: dict[datetime, np.ndarray],
    train_end: datetime,
    seed: int,
    history_hours: int,
) -> list[V2Record]:
    """Collect v2 records using a shorter history whose last daily state is d=4."""
    by_time = {point.measured_at: point for point in points}
    origins = [
        point.measured_at
        for point in points
        if point.measured_at > train_end
        and point.measured_at.hour == 0
        and int((point.measured_at - train_end).total_seconds() // 3600) % DEFAULT_STRIDE_HOURS == 0
        and point.siips > 0.0
    ]
    records: list[V2Record] = []
    torch.manual_seed(seed)
    for origin in origins:
        history_origin = history_window_origin(artifacts, origin)
        history = history_frame(feature_rows, origin=history_origin, length=history_hours)
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


def fixed_origins(
    *,
    points: list[CareLoadPoint],
    train_end: datetime,
    feature_rows: dict[datetime, np.ndarray],
    limit: int,
    length: int,
) -> list[datetime]:
    """Return the first fixed valid daily origins with complete history."""
    origins: list[datetime] = []
    for point in points:
        origin = point.measured_at
        if not (
            origin > train_end
            and origin.hour == 0
            and int((origin - train_end).total_seconds() // 3600) % DEFAULT_STRIDE_HOURS == 0
            and point.siips > 0.0
        ):
            continue
        start = origin - timedelta(hours=length)
        complete = all(start + timedelta(hours=offset) in feature_rows for offset in range(length))
        if complete:
            origins.append(origin)
        if len(origins) >= limit:
            break
    return origins


def state_norm_pattern(means: dict[str, float]) -> str:
    """Classify the simple directional state-norm pattern."""
    ordered = [means[f"d{index}"] for index in range(7)]
    if all(ordered[index] <= ordered[index + 1] for index in range(len(ordered) - 1)):
        return "monotonic_increase"
    if all(ordered[index] >= ordered[index + 1] for index in range(len(ordered) - 1)):
        return "monotonic_decrease"
    return "non_monotonic"


def print_aligned_table(report: dict[str, Any]) -> None:
    """Print aligned vs misaligned diagnostic rows."""
    print("horizon | model | alignment | mae | mae_ci_95 | coverage_90 | mean_interval_width")
    for horizon in ("24", "48"):
        for key in ("v2-daily-5k-aligned-d4", "v2-daily-500-aligned-d4"):
            metrics = report["aligned_re_eval"]["results"][key]["horizons"][horizon]
            print_metric_row_with_alignment(horizon, key, "aligned d=4", metrics)
        print_misaligned_row(horizon, "v2-daily-5k", MISALIGNED_DAILY_5K_MAE[horizon])
        print_misaligned_row(horizon, "v2-daily-500", MISALIGNED_DAILY_500_MAE[horizon])
    existing_daily_5k = load_eval_summary(DAILY_5K_DIR / "eval_v2.json")
    if existing_daily_5k is not None:
        print(
            "\nexisting misaligned full metrics loaded from "
            "artifacts/v2_forecast_daily_5k/eval_v2.json"
        )
        for horizon in ("24", "48"):
            print_metric_row(
                horizon,
                "v2-daily-5k",
                existing_daily_5k["metrics"]["horizons"][horizon],
            )


def print_metric_row_with_alignment(
    horizon: str,
    label: str,
    alignment: str,
    metrics: dict[str, Any],
) -> None:
    """Print one aligned model metric row."""
    ci = metrics["mae_ci_95"]
    print(
        f"{horizon:>7} | {label:<24} | {alignment:<11} | {metrics['mae']:.2f} | "
        f"[{ci[0]:.2f}, {ci[1]:.2f}] | {metrics['coverage90']:.3f} | "
        f"{metrics['mean_interval_width']:.2f}"
    )


def print_misaligned_row(horizon: str, label: str, mae: float) -> None:
    """Print the known misaligned MAE reference row."""
    print(
        f"{horizon:>7} | {label:<24} | d=6 ref     | {mae:.2f} | "
        "see eval_v2.json | see eval_v2.json | see eval_v2.json"
    )


if __name__ == "__main__":
    main()
