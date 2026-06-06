"""Training entrypoint for the CarePredict TFT model."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import structlog
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

LOGGER = structlog.get_logger(__name__)
app = typer.Typer(no_args_is_help=False)


@app.command()
def main(
    data_path: Path | None = None,
    report_path: Path = Path("reports/backtesting/carepredict_backtest.html"),
    enforce_targets: bool = False,
) -> None:
    """Train TFT, calibrate conformal intervals on real model predictions and log MLflow."""
    frame = load_synthetic_training_frame(data_path)
    split = temporal_split(frame)

    LOGGER.info(
        "training_started",
        train_rows=len(split.train),
        validation_rows=len(split.validation),
        test_rows=len(split.test),
    )

    model = CarePredictTFT()
    train_metrics = model.fit(split.train)
    LOGGER.info("training_finished", backend=model.backend_name, metrics=train_metrics)

    # Use the trained model for validation predictions, then calibrate conformal.
    validation_pred = model.predict_dataframe(
        split.validation,
        history_buffer=split.train.tail(model.config.max_encoder_length * 4),
    )
    conformal = ConformalForecaster()
    conformal.calibrate(
        split.validation["siips_score"].astype(float),
        validation_pred.astype(float),
    )

    # Use the trained model for test predictions, then compute final metrics.
    test_pred = model.predict_dataframe(
        split.test,
        history_buffer=pd.concat(
            [split.train.tail(model.config.max_encoder_length * 4), split.validation],
            ignore_index=True,
        ),
    )
    intervals = conformal.predict_intervals(test_pred.astype(float))
    metrics = calculate_metrics(
        split.test["siips_score"].astype(float),
        test_pred.astype(float),
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
    typer.echo(
        f"trained {model.config.model_version}; backend={model.backend_name}; report={report}"
    )


if __name__ == "__main__":
    app()
