"""Real-history HTTP realism check for POST /forecast/charge."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import torch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.routers.forecast import router
from services.ml.forecasting.v2_forecast import (
    DEFAULT_V2_FORECAST_ARTIFACT_DIR,
    ensure_hospitalos_importable,
    history_window_origin,
    load_v2_forecast_artifacts,
    predict_v2_from_history,
    v2_forecast_history_length,
)

ensure_hospitalos_importable()

from hospitalos.data.timescale_adapter import (  # noqa: E402
    CHANNEL_NAMES,
    TimescaleDatasetConfig,
    TimescaleHospitalDataset,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse realism-check CLI arguments."""
    parser = argparse.ArgumentParser(description="Run a real-history /forecast/charge check.")
    parser.add_argument("--service-id", type=str, default="urg-001")
    parser.add_argument("--hospital-id", type=str, default="hosp-001")
    parser.add_argument("--origin", type=str, default="2025-07-08T00:00:00+00:00")
    parser.add_argument("--train-end", type=str, default="2025-07-01")
    parser.add_argument("--horizon", type=int, default=48)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_V2_FORECAST_ARTIFACT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    """Run the real-history HTTP forecast check and print a JSON report."""
    args = parse_args(argv)
    origin = _parse_utc(args.origin)
    artifacts = load_v2_forecast_artifacts(args.artifact_dir)
    rows = _fetch_rows(service_id=args.service_id, train_end=args.train_end)
    by_time = {row["measured_at"]: row for row in rows}
    history_rows = _history_rows(artifacts=artifacts, by_time=by_time, origin=origin)
    payload = {
        "hospital_id": args.hospital_id,
        "service_id": args.service_id,
        "origin_timestamp": origin.isoformat(),
        "history": history_rows,
        "horizon": args.horizon,
    }

    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post("/forecast/charge", json=payload)
    response.raise_for_status()
    response_json = response.json()

    history_tensor = torch.tensor(
        [[step[name] for name in CHANNEL_NAMES] for step in history_rows],
        dtype=torch.float32,
    ).reshape(1, len(history_rows), len(CHANNEL_NAMES))
    torch.manual_seed(0)
    eval_forecast = predict_v2_from_history(artifacts.model, history_tensor, origin)
    predictions = np.asarray(
        [float(step["predicted_siips"]) for step in response_json["results"]],
        dtype=np.float64,
    )
    truths = np.asarray(
        [
            float(by_time[origin + timedelta(hours=step)]["siips"])
            for step in range(1, args.horizon + 1)
        ],
        dtype=np.float64,
    )
    eval_values = eval_forecast[: args.horizon].numpy().astype(np.float64)
    positive_siips = np.asarray(
        [
            float(row["siips"])
            for row in rows
            if row["siips"] is not None and float(row["siips"]) > 0.0
        ],
        dtype=np.float64,
    )

    report = {
        "origin": origin.isoformat(),
        "service_id": args.service_id,
        "history_length": len(history_rows),
        "channel_names": list(CHANNEL_NAMES),
        "http_status": response.status_code,
        "prediction_band": {
            "min": float(predictions.min()),
            "max": float(predictions.max()),
        },
        "actual_following_band": {
            "min": float(truths.min()),
            "max": float(truths.max()),
        },
        "selected_horizons": {
            str(step): {
                "predicted_siips": float(predictions[step - 1]),
                "actual_siips": float(truths[step - 1]),
                "absolute_error": float(abs(predictions[step - 1] - truths[step - 1])),
            }
            for step in (1, 24, 48)
            if step <= args.horizon
        },
        "eval_path_match": {
            "max_abs_diff_http_vs_shared_eval": float(np.max(np.abs(predictions - eval_values))),
            "matches": bool(np.array_equal(predictions, eval_values)),
        },
        "clinical_guard_band_used_in_tests": {
            "lower_inclusive": 100.0,
            "upper_exclusive": 2000.0,
            "basis": {
                "positive_siips_p01": float(np.quantile(positive_siips, 0.01)),
                "positive_siips_p99": float(np.quantile(positive_siips, 0.99)),
            },
        },
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return report


def _fetch_rows(*, service_id: str, train_end: str) -> list[dict[str, Any]]:
    dataset = TimescaleHospitalDataset(
        TimescaleDatasetConfig(split="val", train_end=train_end, services=[service_id])
    )
    return [row for row in dataset._fetch_rows() if row["service_id"] == service_id]  # noqa: SLF001


def _history_rows(
    *,
    artifacts: Any,
    by_time: dict[datetime, dict[str, Any]],
    origin: datetime,
) -> list[dict[str, float]]:
    history_end = history_window_origin(artifacts, origin)
    length = v2_forecast_history_length(artifacts)
    history_start = history_end - timedelta(hours=length - 1)
    history: list[dict[str, float]] = []
    for offset in range(length):
        row = by_time[history_start + timedelta(hours=offset)]
        history.append({name: float(row[name]) for name in CHANNEL_NAMES})
    return history


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


if __name__ == "__main__":
    main()
