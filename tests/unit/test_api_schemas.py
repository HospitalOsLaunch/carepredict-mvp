"""Root-level API schema tests."""

from __future__ import annotations

from services.api.tests.test_prediction_schema import (
    test_prediction_request_accepts_planned_interventions,
    test_prediction_response_schema_exact_keys,
)

__all__ = [
    "test_prediction_request_accepts_planned_interventions",
    "test_prediction_response_schema_exact_keys",
]
