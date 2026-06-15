"""Hybrid temporal/static state encoder for CarePredict.

The encoder follows the pass 2 contract exactly:

- temporal branch: two-layer GRU, hidden size 256 by default
- static branch: MLP ending at 128 dimensions by default
- fusion: concat 256 + 128 = 384, projected to a 512D state vector
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from typing import cast

import torch
from torch import Tensor, nn


@dataclass(frozen=True, slots=True)
class HybridStateEncoderConfig:
    """Configuration for :class:`HybridStateEncoder`."""

    temporal_features: int
    static_features: int
    sequence_length: int = 24
    gru_hidden_size: int = 256
    gru_layers: int = 2
    gru_dropout: float = 0.1
    static_hidden_size: int = 256
    static_embedding_size: int = 128
    static_dropout: float = 0.1
    state_size: int = 512
    fusion_dropout: float = 0.1

    def __post_init__(self) -> None:
        """Validate dimensions early so model wiring errors fail loudly."""
        positive_fields = {
            "temporal_features": self.temporal_features,
            "static_features": self.static_features,
            "sequence_length": self.sequence_length,
            "gru_hidden_size": self.gru_hidden_size,
            "gru_layers": self.gru_layers,
            "static_hidden_size": self.static_hidden_size,
            "static_embedding_size": self.static_embedding_size,
            "state_size": self.state_size,
        }
        for field_name, value in positive_fields.items():
            if value <= 0:
                raise ValueError(f"{field_name} must be strictly positive")

        if not 0 <= self.gru_dropout < 1:
            raise ValueError("gru_dropout must be in [0, 1)")
        if not 0 <= self.static_dropout < 1:
            raise ValueError("static_dropout must be in [0, 1)")
        if not 0 <= self.fusion_dropout < 1:
            raise ValueError("fusion_dropout must be in [0, 1)")


class HybridStateEncoder(nn.Module):
    """Encode temporal and static care-service context into a 512D state vector."""

    def __init__(
        self,
        config: HybridStateEncoderConfig | None = None,
        *,
        temporal_features: int | None = None,
        static_features: int | None = None,
        sequence_length: int = 24,
        gru_hidden_size: int = 256,
        gru_layers: int = 2,
        gru_dropout: float = 0.1,
        static_hidden_size: int = 256,
        static_embedding_size: int = 128,
        static_dropout: float = 0.1,
        state_size: int = 512,
        fusion_dropout: float = 0.1,
    ) -> None:
        super().__init__()
        if config is None:
            if temporal_features is None or static_features is None:
                raise ValueError(
                    "Either config or both temporal_features and static_features must be provided"
                )
            config = HybridStateEncoderConfig(
                temporal_features=temporal_features,
                static_features=static_features,
                sequence_length=sequence_length,
                gru_hidden_size=gru_hidden_size,
                gru_layers=gru_layers,
                gru_dropout=gru_dropout,
                static_hidden_size=static_hidden_size,
                static_embedding_size=static_embedding_size,
                static_dropout=static_dropout,
                state_size=state_size,
                fusion_dropout=fusion_dropout,
            )
        elif temporal_features is not None or static_features is not None:
            raise ValueError(
                "Do not pass temporal_features/static_features when config is provided"
            )

        self.config = config

        gru_dropout = config.gru_dropout if config.gru_layers > 1 else 0.0
        self.gru = nn.GRU(
            input_size=config.temporal_features,
            hidden_size=config.gru_hidden_size,
            num_layers=config.gru_layers,
            batch_first=True,
            dropout=gru_dropout,
        )
        self.mlp_static = nn.Sequential(
            nn.Linear(config.static_features, config.static_hidden_size),
            nn.ReLU(),
            nn.Dropout(config.static_dropout),
            nn.Linear(config.static_hidden_size, config.static_embedding_size),
            nn.ReLU(),
        )

        fused_size = config.gru_hidden_size + config.static_embedding_size
        self.state_vector = nn.Sequential(
            nn.Linear(fused_size, config.state_size),
            nn.LayerNorm(config.state_size),
            nn.Dropout(config.fusion_dropout),
        )

    def forward(self, temporal_input: Tensor, static_input: Tensor) -> Tensor:
        """Return the fused state vector.

        Args:
            temporal_input: tensor shaped ``(batch, seq_len, temporal_features)``.
            static_input: tensor shaped ``(batch, static_features)``.

        Returns:
            Tensor shaped ``(batch, state_size)``.
        """
        self._validate_forward_inputs(temporal_input, static_input)

        temporal_sequence = cast(tuple[Tensor, Tensor], self.gru(temporal_input))[0]
        temporal_embedding = temporal_sequence[:, -1, :]
        static_embedding = self.mlp_static(static_input)
        fused = torch.cat([temporal_embedding, static_embedding], dim=-1)
        return cast(Tensor, self.state_vector(fused))

    def _validate_forward_inputs(self, temporal_input: Tensor, static_input: Tensor) -> None:
        """Validate runtime tensor ranks and dimensions."""
        if temporal_input.ndim != 3:
            raise ValueError("temporal_input must have shape (batch, seq_len, features)")
        if static_input.ndim != 2:
            raise ValueError("static_input must have shape (batch, features)")
        if temporal_input.shape[0] != static_input.shape[0]:
            raise ValueError("temporal_input and static_input batch sizes must match")
        if temporal_input.shape[1] != self.config.sequence_length:
            raise ValueError("temporal_input sequence length does not match encoder configuration")
        if temporal_input.shape[2] != self.config.temporal_features:
            raise ValueError("temporal_input feature count does not match encoder configuration")
        if static_input.shape[1] != self.config.static_features:
            raise ValueError("static_input feature count does not match encoder configuration")


def benchmark_forward_p99_ms(
    model: HybridStateEncoder,
    temporal_input: Tensor,
    static_input: Tensor,
    *,
    warmup_runs: int = 10,
    measured_runs: int = 100,
) -> float:
    """Measure p99 forward-pass latency in milliseconds on the current device."""
    if warmup_runs < 0:
        raise ValueError("warmup_runs must be non-negative")
    if measured_runs <= 1:
        raise ValueError("measured_runs must be greater than 1")

    model.eval()
    durations_ms: list[float] = []

    with torch.inference_mode():
        for _ in range(warmup_runs):
            _ = model(temporal_input, static_input)

        for _ in range(measured_runs):
            start_ns = time.perf_counter_ns()
            _ = model(temporal_input, static_input)
            end_ns = time.perf_counter_ns()
            durations_ms.append((end_ns - start_ns) / 1_000_000)

    quantiles = statistics.quantiles(durations_ms, n=100, method="inclusive")
    return quantiles[98]
