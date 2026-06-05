"""Root-level pass 2 encoder tests."""

from __future__ import annotations

from services.ml.encoders.tests.test_hybrid_encoder import (
    test_hybrid_encoder_backpropagates_gradients,
    test_hybrid_encoder_forward_p99_latency_under_20ms_cpu,
    test_hybrid_encoder_output_shape,
    test_hybrid_encoder_rejects_wrong_temporal_shape,
    test_hybrid_encoder_reproducible_with_seed_in_eval_mode,
)

__all__ = [
    "test_hybrid_encoder_backpropagates_gradients",
    "test_hybrid_encoder_forward_p99_latency_under_20ms_cpu",
    "test_hybrid_encoder_output_shape",
    "test_hybrid_encoder_rejects_wrong_temporal_shape",
    "test_hybrid_encoder_reproducible_with_seed_in_eval_mode",
]
