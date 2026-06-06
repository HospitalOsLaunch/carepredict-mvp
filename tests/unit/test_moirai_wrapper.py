"""Root-level tests for the Moirai wrapper."""

from __future__ import annotations

from services.ml.models.tests.test_moirai_wrapper import (
    test_moirai_config_validates_checkpoint_path,
    test_moirai_fine_tune_returns_metrics_without_mlflow_dependency,
    test_moirai_predict_returns_horizon_values,
    test_moirai_predict_with_metadata_uses_stable_version,
    test_moirai_rejects_empty_history,
    test_moirai_rejects_invalid_horizon,
)

__all__ = [
    "test_moirai_config_validates_checkpoint_path",
    "test_moirai_fine_tune_returns_metrics_without_mlflow_dependency",
    "test_moirai_predict_returns_horizon_values",
    "test_moirai_predict_with_metadata_uses_stable_version",
    "test_moirai_rejects_empty_history",
    "test_moirai_rejects_invalid_horizon",
]
