"""Delayed batch CUSUM, jointly calibrated on independent stable trajectories.

ARL is measured in informative episode batches, not individual correlated labels.
Finite simulation estimates restricted run length, never an anytime guarantee.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

import numpy as np

from .continuous import Array, log_loss
from .robustness_models import LOCK, WEIGHT_AVAILABLE, Experts, cohort

ARL_TARGET = 200
CALIBRATION_SEEDS = tuple(range(3000, 3128))
VALIDATION_SEEDS = tuple(range(4000, 4128))
CALIBRATION_LENGTH = 1000
MARGIN = 0.05


@dataclass(frozen=True)
class CusumSettings:
    center: tuple[float, float]
    scale: tuple[float, float]
    threshold: float
    available_at: datetime = LOCK

    def __post_init__(self) -> None:
        if self.available_at.tzinfo is None or not all(
            math.isfinite(v) for v in (*self.center, *self.scale, self.threshold)
        ):
            raise ValueError("Invalid monitor settings")
        if min(self.scale) <= 0 or self.threshold <= 0:
            raise ValueError("Positive scale/threshold required")


def losses(experts: Experts, alpha: float, seed: int, length: int, origin: datetime) -> Array:
    data = cohort(seed, length, origin)
    if data.origin < WEIGHT_AVAILABLE or data.last_label_at > LOCK:
        raise ValueError("Alarm development crosses information boundaries")
    predicted = experts.predict(data.features)
    reference = log_loss(predicted["pooled"], data.time, data.observed)
    mixture = log_loss(predicted["pooled"], data.time, data.observed, predicted["boosting"], alpha)
    return cast(
        Array,
        np.c_[
            (mixture - reference).reshape(-1, 3).mean(axis=1), reference.reshape(-1, 3).mean(axis=1)
        ],
    )


def run_lengths(values: Array, settings: CusumSettings) -> Array:
    state = np.zeros((len(values), 2))
    length = np.full(len(values), values.shape[1] + 1, dtype=int)
    for i in range(values.shape[1]):
        state = np.maximum(0, state + (values[:, i] - settings.center - MARGIN) / settings.scale)
        crossed = np.any(state > settings.threshold, axis=1) & (length > values.shape[1])
        length[crossed] = i + 1
    return length


def summarize_lengths(length: Array, horizon: int) -> dict[str, Any]:
    restricted = np.minimum(length, horizon)
    rng = np.random.default_rng(82001)
    sample = rng.integers(0, len(length), (2000, len(length)))
    interval = np.quantile(restricted[sample].mean(axis=1), (0.025, 0.975))
    return {
        "trajectories": len(length),
        "horizon_batches": horizon,
        "restricted_mean_run_length": float(restricted.mean()),
        "restricted_mean_ci95": interval.tolist(),
        "right_censored_fraction": float(np.mean(length > horizon)),
        "false_alarm_probability_first_48_batches": float(np.mean(length <= 48)),
        "arl_target": ARL_TARGET,
        "arl_exact": None,
        "target_supported_by_validation_lower_bound": bool(interval[0] >= ARL_TARGET),
    }


def calibrate_cusum(experts: Experts, alpha: float) -> tuple[CusumSettings, dict[str, Any]]:
    from datetime import UTC

    centering = losses(experts, alpha, 2501, 96, datetime(2026, 8, 15, tzinfo=UTC))
    center = tuple(float(v) for v in centering.mean(axis=0))
    scale = tuple(float(max(v, 0.01)) for v in centering.std(axis=0, ddof=1))
    origin = datetime(2026, 8, 26, tzinfo=UTC)
    values = np.stack(
        [losses(experts, alpha, s, CALIBRATION_LENGTH, origin) for s in CALIBRATION_SEEDS]
    )
    low, high = 0.0, 128.0
    for _ in range(15):
        threshold = (low + high) / 2
        settings = CusumSettings((center[0], center[1]), (scale[0], scale[1]), threshold)
        lengths = run_lengths(values, settings)
        if np.minimum(lengths, CALIBRATION_LENGTH).mean() >= ARL_TARGET:
            high = threshold
        else:
            low = threshold
    settings = CusumSettings((center[0], center[1]), (scale[0], scale[1]), high)
    calibration = summarize_lengths(run_lengths(values, settings), CALIBRATION_LENGTH)
    # The reserved stable validation estimates the operating point; it never retunes h.
    validation_values = np.stack(
        [losses(experts, alpha, s, CALIBRATION_LENGTH, origin) for s in VALIDATION_SEEDS]
    )
    validation = summarize_lengths(run_lengths(validation_values, settings), CALIBRATION_LENGTH)
    return settings, {"calibration": calibration, "stable_validation": validation}


@dataclass(frozen=True)
class BatchFeedback:
    episode_id: str
    origin: datetime
    available_at: datetime
    paired_loss: float
    reference_loss: float


class DelayedCusum:
    def __init__(self, settings: CusumSettings):
        self.settings = settings
        self.clock = settings.available_at
        self.state = np.zeros(2)
        self.seen: set[str] = set()
        self.fallback_at: datetime | None = None
        self.suspended_at: datetime | None = None

    def observe(self, feedback: BatchFeedback, at: datetime) -> None:
        if at.tzinfo is None or at < self.clock:
            raise ValueError("Invalid or backward monitor clock")
        if feedback.origin < self.settings.available_at or feedback.available_at > at:
            raise ValueError("Unavailable or pre-lock feedback")
        if feedback.available_at < feedback.origin + timedelta(hours=24):
            raise ValueError("Missing 24-hour feedback embargo")
        if feedback.episode_id in self.seen:
            raise ValueError("Duplicate feedback episode")
        values = np.array([feedback.paired_loss, feedback.reference_loss])
        if not np.all(np.isfinite(values)):
            raise ValueError("Non-finite feedback")
        self.clock = at
        self.seen.add(feedback.episode_id)
        self.state = np.maximum(
            0, self.state + (values - self.settings.center - MARGIN) / self.settings.scale
        )
        if self.state[0] > self.settings.threshold and self.fallback_at is None:
            self.fallback_at = at
        if self.state[1] > self.settings.threshold and self.suspended_at is None:
            self.suspended_at = at
