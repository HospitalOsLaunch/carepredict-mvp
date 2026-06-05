"""Tests for the hybrid GRU + MLP state encoder."""

from __future__ import annotations

import os

import pytest
import torch

from services.ml.encoders.hybrid_encoder import (
    HybridStateEncoder,
    HybridStateEncoderConfig,
    benchmark_forward_p99_ms,
)


def _build_encoder() -> HybridStateEncoder:
    config = HybridStateEncoderConfig(temporal_features=14, static_features=9)
    return HybridStateEncoder(config)


def test_hybrid_encoder_output_shape() -> None:
    model = _build_encoder()
    temporal = torch.randn(8, 24, 14)
    static = torch.randn(8, 9)

    output = model(temporal, static)

    assert output.shape == (8, 512)


def test_hybrid_encoder_backpropagates_gradients() -> None:
    model = _build_encoder()
    temporal = torch.randn(4, 24, 14, requires_grad=True)
    static = torch.randn(4, 9, requires_grad=True)

    loss = model(temporal, static).pow(2).mean()
    loss.backward()

    assert temporal.grad is not None
    assert static.grad is not None
    assert temporal.grad.abs().sum().item() > 0
    assert static.grad.abs().sum().item() > 0

    parameter_gradients = [
        parameter.grad
        for parameter in model.parameters()
        if parameter.requires_grad and parameter.grad is not None
    ]
    assert parameter_gradients
    assert sum(gradient.abs().sum().item() for gradient in parameter_gradients) > 0


def test_hybrid_encoder_reproducible_with_seed_in_eval_mode() -> None:
    torch.manual_seed(20260606)
    model_a = _build_encoder().eval()
    temporal = torch.randn(2, 24, 14)
    static = torch.randn(2, 9)
    output_a = model_a(temporal, static)

    torch.manual_seed(20260606)
    model_b = _build_encoder().eval()
    output_b = model_b(temporal, static)

    assert torch.allclose(output_a, output_b)


def test_hybrid_encoder_rejects_wrong_temporal_shape() -> None:
    model = _build_encoder()
    temporal = torch.randn(4, 12, 14)
    static = torch.randn(4, 9)

    with pytest.raises(ValueError, match="sequence length"):
        model(temporal, static)


@pytest.mark.performance
def test_hybrid_encoder_forward_p99_latency_under_20ms_cpu() -> None:
    if os.getenv("CAREPREDICT_SKIP_PERF_TESTS") == "1":
        pytest.skip("performance tests disabled by environment")

    torch.set_num_threads(1)
    model = _build_encoder()
    temporal = torch.randn(1, 24, 14)
    static = torch.randn(1, 9)

    p99_ms = benchmark_forward_p99_ms(
        model,
        temporal,
        static,
        warmup_runs=10,
        measured_runs=100,
    )

    assert p99_ms < 20.0
