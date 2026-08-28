"""Frozen deterministic HFWM-R0 evaluation metrics."""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class PointMetrics:
    """Point forecast metrics computed on one frozen cohort."""

    count: int
    mae: float
    rmse: float
    smape: float


def point_metrics(truth: Sequence[float], prediction: Sequence[float]) -> PointMetrics:
    """Compute MAE, RMSE and bounded symmetric MAPE."""
    _validate_pairs(truth, prediction)
    errors = [
        abs(float(actual) - float(predicted))
        for actual, predicted in zip(truth, prediction, strict=True)
    ]
    squared = [
        (float(actual) - float(predicted)) ** 2
        for actual, predicted in zip(truth, prediction, strict=True)
    ]
    smape_terms = [
        0.0
        if abs(float(actual)) + abs(float(predicted)) == 0.0
        else 2.0 * abs(float(actual) - float(predicted))
        / (abs(float(actual)) + abs(float(predicted)))
        for actual, predicted in zip(truth, prediction, strict=True)
    ]
    return PointMetrics(
        count=len(errors),
        mae=math.fsum(errors) / len(errors),
        rmse=math.sqrt(math.fsum(squared) / len(squared)),
        smape=math.fsum(smape_terms) / len(smape_terms),
    )


def pinball_loss(truth: Sequence[float], prediction: Sequence[float], *, quantile: float) -> float:
    """Compute mean pinball loss for one quantile."""
    _validate_pairs(truth, prediction)
    if not 0.0 < quantile < 1.0:
        raise ValueError("quantile must be in (0, 1)")
    values = []
    for actual, predicted in zip(truth, prediction, strict=True):
        residual = float(actual) - float(predicted)
        values.append(max(quantile * residual, (quantile - 1.0) * residual))
    return math.fsum(values) / len(values)


def interval_coverage(
    truth: Sequence[float], lower: Sequence[float], upper: Sequence[float]
) -> float:
    """Compute empirical interval coverage after validating interval order."""
    _validate_pairs(truth, lower)
    _validate_pairs(truth, upper)
    for low, high in zip(lower, upper, strict=True):
        if float(low) > float(high):
            raise ValueError("lower interval bound exceeds upper bound")
    covered = [
        float(low) <= float(actual) <= float(high)
        for actual, low, high in zip(truth, lower, upper, strict=True)
    ]
    return math.fsum(float(value) for value in covered) / len(covered)


def relative_gain(*, candidate_score: float, comparator_score: float) -> float:
    """Return relative error reduction for lower-is-better scores."""
    if not math.isfinite(candidate_score) or not math.isfinite(comparator_score):
        raise ValueError("scores must be finite")
    if comparator_score <= 0.0:
        raise ValueError("comparator_score must be positive")
    return (comparator_score - candidate_score) / comparator_score


def bootstrap_relative_gain_ci(
    candidate_losses: Sequence[float],
    comparator_losses: Sequence[float],
    *,
    seed: int,
    draws: int = 2000,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Return a seeded paired percentile interval for relative gain."""
    _validate_pairs(candidate_losses, comparator_losses)
    if draws <= 0:
        raise ValueError("draws must be positive")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")
    size = len(candidate_losses)
    generator = random.Random(seed)
    gains: list[float] = []
    for _ in range(draws):
        indexes = [generator.randrange(size) for _ in range(size)]
        candidate = math.fsum(float(candidate_losses[index]) for index in indexes) / size
        comparator = math.fsum(float(comparator_losses[index]) for index in indexes) / size
        if comparator <= 0.0:
            raise ValueError("bootstrapped comparator mean must be positive")
        gains.append(relative_gain(candidate_score=candidate, comparator_score=comparator))
    gains.sort()
    lower_index = max(0, math.floor((alpha / 2.0) * draws))
    upper_index = min(draws - 1, math.ceil((1.0 - alpha / 2.0) * draws) - 1)
    return gains[lower_index], gains[upper_index]


def _validate_pairs(left: Sequence[float], right: Sequence[float]) -> None:
    if not left or len(left) != len(right):
        raise ValueError("metric inputs must be non-empty and have equal lengths")
    if any(not math.isfinite(float(value)) for value in (*left, *right)):
        raise ValueError("metric inputs must be finite")
