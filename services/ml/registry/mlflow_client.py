"""Small MLflow client wrapper for CarePredict models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import structlog

LOGGER = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class MLflowModelRegistry:
    """Log and load model metadata from MLflow when available."""

    tracking_uri: str | None = None
    experiment_name: str = "carepredict-training"

    def log_training_run(
        self,
        *,
        run_name: str,
        params: Mapping[str, str | int | float | bool],
        metrics: Mapping[str, float],
        artifacts: list[Path] | None = None,
        tags: Mapping[str, str] | None = None,
    ) -> str:
        """Log a training run and return the MLflow run id, or ``offline``."""
        try:
            import mlflow
        except ImportError:
            LOGGER.info("mlflow_not_installed_skipping_training_log", run_name=run_name)
            return "offline"

        if self.tracking_uri is not None:
            mlflow.set_tracking_uri(self.tracking_uri)
        mlflow.set_experiment(self.experiment_name)
        with mlflow.start_run(run_name=run_name) as run:
            mlflow.log_params(dict(params))
            mlflow.log_metrics(dict(metrics))
            if tags:
                mlflow.set_tags(dict(tags))
            for artifact in artifacts or []:
                if artifact.exists():
                    mlflow.log_artifact(str(artifact))
            return str(run.info.run_id)
