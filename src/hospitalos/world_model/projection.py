"""Reconstruct counterfactual ward censuses after the simulated report is published."""

from __future__ import annotations

import numpy as np


def _bed_simplex(values: np.ndarray, capacity: np.ndarray) -> np.ndarray:
    """Euclidean projection onto nonnegative bed stocks whose sum is at most capacity.

    Center before scaling to preserve equal allocations even for huge tied predictions.
    """
    positive = np.maximum(values, 0.0)
    limit = np.broadcast_to(np.asarray(capacity, dtype=float), positive.shape[:-1])[..., None]
    peak = positive.max(axis=-1, keepdims=True)
    fits = (peak <= limit) & (np.minimum(positive, limit).sum(axis=-1, keepdims=True) <= limit)
    scale = np.where(limit > 0, limit, 1.0)
    centered = np.maximum(positive - peak, -scale) / scale
    ordered = np.sort(centered, axis=-1)[..., ::-1]
    levels = (ordered.cumsum(-1) - 1.0) / np.arange(1, ordered.shape[-1] + 1)
    last = (ordered > levels).sum(-1, keepdims=True) - 1
    threshold = np.take_along_axis(levels, last, axis=-1)
    projected = np.maximum(centered - threshold, 0.0) * limit
    return np.asarray(np.where(fits, positive, projected))


def _clock(value: int) -> bool:
    return (
        isinstance(value, (int, np.integer))
        and not isinstance(value, (bool, np.bool_))
        and value >= 0
    )


def reconstruct(
    predicted: np.ndarray,
    factual: int,
    observed: np.ndarray,
    mask: np.ndarray,
    beds: np.ndarray,
    *,
    now: int,
    published: int,
) -> np.ndarray:
    """Anchor only after receipt. Preserve the measured cells of the executed action."""
    x = np.asarray(predicted, dtype=float)
    caps = np.asarray(beds, dtype=float)
    visible = np.asarray(mask)
    if (
        x.ndim != 3
        or not x.shape[1] >= 1
        or x.shape[-1] != 5
        or not _clock(factual)
        or factual >= len(x)
        or not _clock(now)
        or not _clock(published)
        or not np.isfinite(x).all()
        or caps.shape != (x.shape[1],)
        or not np.isfinite(caps).all()
        or np.any((caps <= 0) | (caps > 1_000_000))
    ):
        raise ValueError("Invalid forecast, capacities, factual option or clock")
    prior = x.copy()
    if now >= published:
        y = np.asarray(observed, dtype=float)
        if (
            y.shape != x.shape[1:]
            or visible.shape != y.shape
            or visible.dtype != np.bool_
            or not np.array_equal(np.isfinite(y), visible)
            or np.any(y[visible] < -1e-7)
            or np.any(np.where(visible[:, 1:], y[:, 1:], 0.0).sum(-1) > caps + 1e-7)
        ):
            raise ValueError("Published census conflicts with its coverage or bed capacity")
        prior += np.where(visible, y - x[factual], 0.0)
        if not np.isfinite(prior).all():
            raise ValueError("Unrepresentable action contrast")
    result = np.maximum(prior, 0.0)
    result[..., 1:] = _bed_simplex(prior[..., 1:], caps)
    if now >= published:
        for i, known in enumerate(visible[:, 1:]):
            if visible[i, 0]:
                result[factual, i, 0] = max(0.0, y[i, 0])
            row = result[factual, i, 1:]
            row[known] = np.maximum(0.0, y[i, 1:][known])
            if known.any() and not known.all():
                left = max(0.0, caps[i] - row[known].sum())
                row[~known] = _bed_simplex(prior[factual, i, 1:][~known], left)
    return np.asarray(result)
