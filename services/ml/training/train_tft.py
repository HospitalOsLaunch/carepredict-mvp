"""Training entrypoint for the CarePredict TFT model."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import structlog
import typer

from services.ml.models.tft_model import CarePredictTFT, PytorchForecastingTFTBackend, TFTConfig
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

BUNDLE_PATH = Path("/app/checkpoints/model_bundle.pkl")


@app.command()
def main(
    data_path: Path | None = None,
    report_path: Path = Path("reports/backtesting/carepredict_backtest.html"),
    bundle_path: Path = BUNDLE_PATH,
    enforce_targets: bool = False,
    target_column: str = "siips_score",
) -> None:
    """Train TFT, calibrate conformal intervals on real model predictions and log MLflow."""
    frame = load_synthetic_training_frame(data_path)
    split = temporal_split(frame)
    config = TFTConfig(target_column=target_column)

    LOGGER.info(
        "training_started",
        train_rows=len(split.train),
        validation_rows=len(split.validation),
        test_rows=len(split.test),
    )

    model = CarePredictTFT(config=config)
    train_metrics = model.fit(split.train)
    LOGGER.info("training_finished", backend=model.backend_name, metrics=train_metrics)

    if isinstance(model._backend, PytorchForecastingTFTBackend):
        try:
            model._backend.save_bundle(bundle_path)
            LOGGER.info("serving_bundle_persisted", path=str(bundle_path))
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("serving_bundle_save_failed", error=str(exc))
    else:
        LOGGER.info(
            "serving_bundle_skipped_non_torch_backend",
            backend=model.backend_name,
        )

    validation_pred = model.predict_dataframe(
        split.validation,
        history_buffer=split.train.tail(model.config.max_encoder_length * 4),
    )
    conformal = ConformalForecaster()
    conformal.calibrate(
        split.validation[model.config.target_column].astype(float),
        validation_pred.astype(float),
    )

    test_pred = model.predict_dataframe(
        split.test,
        history_buffer=pd.concat(
            [split.train.tail(model.config.max_encoder_length * 4), split.validation],
            ignore_index=True,
        ),
    )
    intervals = conformal.predict_intervals(test_pred.astype(float))
    metrics = calculate_metrics(
        split.test[model.config.target_column].astype(float),
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
            "target_column": model.config.target_column,
        },
        metrics={**train_metrics, **metrics.as_dict()},
        artifacts=[report],
        tags={"candidate_stage": "shadow"},
    )
    typer.echo(
        f"trained {model.config.model_version}; backend={model.backend_name}; "
        f"report={report}; bundle={bundle_path if bundle_path.exists() else 'not_saved'}"
    )


if __name__ == "__main__":
    app()
