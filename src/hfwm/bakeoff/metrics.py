"""Frozen common-cohort metrics for the offline HFWM-R0 runner."""

from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict
from collections.abc import Iterable, Mapping

import numpy as np

from .contracts import HORIZONS, SEEDS, TASKS, FloatArray, ForecastRecord


def evaluate_forecasts(
    records: Iterable[ForecastRecord],
    *,
    train_iqr: FloatArray,
    bootstrap_draws: int,
) -> dict[str, object]:
    """Evaluate every model/seed with frozen macro and paired-bootstrap metrics."""
    materialized = tuple(records)
    if train_iqr.shape != (len(TASKS),) or np.any(train_iqr <= 0.0):
        raise ValueError("train_iqr must be positive for every preregistered task")
    grouped: dict[tuple[str, int], list[ForecastRecord]] = defaultdict(list)
    for record in materialized:
        _validate_record(record)
        grouped[(record.model_id, record.seed)].append(record)
    by_model: dict[str, dict[str, object]] = defaultdict(dict)
    for (model_id, seed), rows in sorted(grouped.items()):
        by_model[model_id][str(seed)] = _evaluate_model_seed(
            rows,
            train_iqr=train_iqr,
            seed=seed,
            bootstrap_draws=bootstrap_draws,
        )
    result: dict[str, object] = {}
    for model_id, seed_results in sorted(by_model.items()):
        aggregate_values = [
            float(value["aggregate_normalized_mae"])
            for value in seed_results.values()
            if isinstance(value, Mapping)
        ]
        result[model_id] = {
            "status": "EXECUTED",
            "by_seed": dict(seed_results),
            "seed_count": len(seed_results),
            "aggregate_normalized_mae_mean_across_seeds": float(
                np.mean(aggregate_values)
            ),
            "directionally_stable_seed_count": _directionally_stable_count(aggregate_values),
        }
    return result


def assert_common_cohort(
    records: Iterable[ForecastRecord], *, expected_model_ids: tuple[str, ...]
) -> str:
    """Require the exact same window/horizon identity for every model and seed."""
    mutable: dict[tuple[str, int], list[tuple[str, int]]] = defaultdict(list)
    for record in records:
        mutable[(record.model_id, record.seed)].append((record.window_id, record.horizon))
    identities = {key: tuple(sorted(values)) for key, values in mutable.items()}
    expected_pairs = {
        (model_id, seed) for model_id in expected_model_ids for seed in SEEDS
    }
    if set(identities) != expected_pairs:
        raise ValueError("model/seed execution matrix differs from the frozen contract")
    unique = set(identities.values())
    if len(unique) != 1:
        raise ValueError("models were not evaluated on the same window/horizon cohort")
    payload = repr(next(iter(unique))).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _evaluate_model_seed(
    rows: list[ForecastRecord],
    *,
    train_iqr: FloatArray,
    seed: int,
    bootstrap_draws: int,
) -> dict[str, object]:
    ordered = sorted(rows, key=lambda item: (item.window_id, item.horizon))
    cells: dict[str, object] = {}
    normalized_mae_cells: list[float] = []
    normalized_rmse_cells: list[float] = []
    for horizon in HORIZONS:
        horizon_rows = [row for row in ordered if row.horizon == horizon]
        if not horizon_rows:
            raise ValueError(f"missing horizon {horizon}")
        truth = np.stack([row.truth for row in horizon_rows])
        prediction = np.stack([row.prediction for row in horizon_rows])
        absolute = np.abs(truth - prediction)
        squared = (truth - prediction) ** 2
        for feature, task in enumerate(TASKS):
            normalized_mae = float(np.mean(absolute[:, feature]) / train_iqr[feature])
            normalized_rmse = float(
                np.sqrt(np.mean(squared[:, feature])) / train_iqr[feature]
            )
            normalized_mae_cells.append(normalized_mae)
            normalized_rmse_cells.append(normalized_rmse)
            cells[f"{task}@{horizon}h"] = {
                "mae": float(np.mean(absolute[:, feature])),
                "rmse": float(np.sqrt(np.mean(squared[:, feature]))),
                "normalized_mae": normalized_mae,
                "normalized_rmse": normalized_rmse,
                "n_windows": len(horizon_rows),
            }
    coverage: float | str = "NOT_AVAILABLE"
    if all(row.uncertainty is not None for row in ordered):
        covered = []
        z80 = 1.2815515655446004
        for row in ordered:
            uncertainty = row.uncertainty
            assert uncertainty is not None
            covered.extend(
                (np.abs(row.truth - row.prediction) <= z80 * uncertainty).tolist()
            )
        coverage = float(np.mean(covered))
    constraint_violations = 0
    constraint_checks = 0
    for row in ordered:
        negative = bool(np.any(row.prediction < 0.0))
        above_capacity = bool(row.prediction[0] > row.capacity + 1e-9)
        constraint_violations += int(negative or above_capacity)
        constraint_checks += 1
    ci_lower, ci_upper = _bootstrap_aggregate_ci(
        ordered,
        train_iqr=train_iqr,
        seed=seed,
        draws=bootstrap_draws,
    )
    return {
        "aggregate_normalized_mae": float(np.mean(normalized_mae_cells)),
        "aggregate_normalized_rmse": float(np.mean(normalized_rmse_cells)),
        "aggregate_normalized_mae_bootstrap_ci95": [ci_lower, ci_upper],
        "calibration_coverage_80": coverage,
        "hard_constraint_violation_rate": (
            constraint_violations / constraint_checks if constraint_checks else 0.0
        ),
        "free_running": all(row.free_running for row in ordered),
        "trajectory_count": len({row.window_id for row in ordered}),
        "forecast_row_count": len(ordered),
        "cells": cells,
    }


def _bootstrap_aggregate_ci(
    rows: list[ForecastRecord],
    *,
    train_iqr: FloatArray,
    seed: int,
    draws: int,
) -> tuple[float, float]:
    by_window: dict[str, list[ForecastRecord]] = defaultdict(list)
    for row in rows:
        by_window[row.window_id].append(row)
    window_ids = sorted(by_window)
    generator = random.Random(seed)
    scores: list[float] = []
    for _ in range(draws):
        sampled = [window_ids[generator.randrange(len(window_ids))] for _ in window_ids]
        cell_losses: list[list[float]] = [[] for _ in range(len(TASKS) * len(HORIZONS))]
        for window_id in sampled:
            for row in by_window[window_id]:
                horizon_index = HORIZONS.index(row.horizon)
                absolute = np.abs(row.truth - row.prediction) / train_iqr
                for feature in range(len(TASKS)):
                    cell_losses[horizon_index * len(TASKS) + feature].append(
                        float(absolute[feature])
                    )
        scores.append(float(np.mean([np.mean(cell) for cell in cell_losses if cell])))
    scores.sort()
    lower = scores[max(0, math.floor(0.025 * draws))]
    upper = scores[min(draws - 1, math.ceil(0.975 * draws) - 1)]
    return lower, upper


def _validate_record(record: ForecastRecord) -> None:
    expected_shape = (len(TASKS),)
    if record.horizon not in HORIZONS:
        raise ValueError("forecast record uses a non-preregistered horizon")
    if record.truth.shape != expected_shape or record.prediction.shape != expected_shape:
        raise ValueError("forecast vectors must match the preregistered task count")
    if record.uncertainty is not None and record.uncertainty.shape != expected_shape:
        raise ValueError("uncertainty vector has an invalid shape")
    arrays = [record.truth, record.prediction]
    if record.uncertainty is not None:
        arrays.append(record.uncertainty)
    if not all(np.all(np.isfinite(array)) for array in arrays):
        raise ValueError("forecast records must contain finite arrays")
    if record.capacity < 0.0:
        raise ValueError("capacity must be non-negative")


def _directionally_stable_count(values: list[float]) -> int:
    if not values:
        return 0
    reference = values[0]
    return sum(math.isclose(value, reference, rel_tol=1e-10, abs_tol=1e-12) for value in values)
