"""Root-level tests for the TFT wrapper."""

from __future__ import annotations

from services.ml.models.tests.test_tft_model import (
    test_build_future_covariates_maps_intervention_types,
    test_default_siips_target_matches_explicit_siips_target,
    test_real_tft_backend_fits_and_forecasts_any_target,
    test_tft_fit_returns_baseline_metrics,
    test_tft_predict_returns_value_and_attention_features,
    test_tft_rejects_missing_history_columns,
)

__all__ = [
    "test_build_future_covariates_maps_intervention_types",
    "test_default_siips_target_matches_explicit_siips_target",
    "test_real_tft_backend_fits_and_forecasts_any_target",
    "test_tft_fit_returns_baseline_metrics",
    "test_tft_predict_returns_value_and_attention_features",
    "test_tft_rejects_missing_history_columns",
]
