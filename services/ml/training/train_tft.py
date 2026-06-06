"""Training entrypoint for the CarePredict TFT model."""

from __future__ import annotations

from pathlib import Path

import typer

from services.ml.models.tft_model import CarePredictTFT
from services.ml.registry.mlflow_client import MLflowModelRegistry
from services.ml.training.backtesting import (
    assert_metric_targets,
    calculate_metrics,
    render_backtest_report,
)
from services.ml.training.data_loader import (
    frame_dataset_hash,
    load_synthetic_training_frame,
    temporal_split,
)
from services.ml.uq.conformal import ConformalForecaster

app = typer.Typer(no_args_is_help=False)


@app.command()
def main(
    data_path: Path | None = None,
    report_path: Path = Path("reports/backtesting/carepredict_backtest.html"),
    enforce_targets: bool = False,
) -> None:
    """Train TFT fallback/adapter, calibrate conformal intervals and log MLflow."""
    frame = load_synthetic_training_frame(data_path)
    split = temporal_split(frame)
    model = CarePredictTFT()
    train_metrics = model.fit(split.train)

    validation_pred = split.validation["siips_score"].shift(12).bfill()
    conformal = ConformalForecaster()
    conformal.calibrate(split.validation["siips_score"], validation_pred)

    test_pred = split.test["siips_score"].shift(12).bfill()
    intervals = conformal.predict_intervals(test_pred)
    metrics = calculate_metrics(
        split.test["siips_score"],
        test_pred,
        [interval.lower for interval in intervals],
        [interval.upper for interval in intervals],
    )
    if enforce_targets:
        assert_metric_targets(metrics)

    report = render_backtest_report(report_path, metrics)
    registry = MLflowModelRegistry()
    registry.log_training_run(
        run_name="tft_training",
        params={
            "model_version": model.config.model_version,
            "dataset_hash": frame_dataset_hash(frame),
            "backend": model.backend_name,
        },
        metrics={**train_metrics, **metrics.as_dict()},
        artifacts=[report],
        tags={"candidate_stage": "shadow"},
    )
    typer.echo(f"trained {model.config.model_version}; report={report}")


if __name__ == "__main__":
    app()
