"""Pre-registered, non-learned mechanistic comparator for HFWM-R0."""

from .core import (
    MechanisticConfig,
    MechanisticQueueSemiMarkov,
    hard_violation_rate,
)

__all__ = [
    "MechanisticConfig",
    "MechanisticQueueSemiMarkov",
    "hard_violation_rate",
]
