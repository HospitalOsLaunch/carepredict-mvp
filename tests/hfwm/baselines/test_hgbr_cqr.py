from __future__ import annotations

import copy
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from hfwm.baselines import (
    BASELINE_STATUS,
    HORIZONS_HOURS,
    TARGETS,
    ForecastExample,
    FrozenHGBRCQRConfig,
    HGBRCQRBaseline,
    TrajectoryPoint,
)


def _example(prefix: str, index: int, *, target_offset: float = 0.0) -> ForecastExample:
    origin = datetime(2025, 1, 1, tzinfo=UTC) + timedelta(days=index)
    history = tuple(
        TrajectoryPoint(
            record_id=f"{prefix}-{index}-past-{step}",
            observed_at=origin - timedelta(hours=8 - step),
            available_at=origin - timedelta(hours=8 - step) + timedelta(minutes=10),
            values={
                "occupancy": 30.0 + index % 9 + step * 0.4,
                "inflow": 2.0 + (index + step) % 5,
                "discharges": 1.0 + (2 * index + step) % 4,
                "staffing": 7.0 + index % 3,
                "pressure": 4_000.0 + 30.0 * index + step,
            },
        )
        for step in range(8)
    )
    targets = {
        target: {
            horizon: (
                target_offset
                + 10.0 * target_index
                + 0.3 * index
                + 0.02 * horizon
            )
            for horizon in HORIZONS_HOURS
        }
        for target_index, target in enumerate(TARGETS)
    }
    return ForecastExample(
        row_id=f"{prefix}-{index}",
        episode_id=f"episode-{prefix}-{index}",
        site_id=f"site-{index % 2}",
        origin_at=origin,
        history=history,
        future_targets=targets,
    )


@pytest.fixture(scope="module")
def splits() -> tuple[tuple[ForecastExample, ...], ...]:
    return (
        tuple(_example("train", index) for index in range(30)),
        tuple(_example("validation", 100 + index) for index in range(12)),
        tuple(_example("test", 200 + index) for index in range(4)),
    )


@pytest.fixture(scope="module")
def fitted(
    splits: tuple[tuple[ForecastExample, ...], ...],
) -> HGBRCQRBaseline:
    train, validation, _ = splits
    return HGBRCQRBaseline().fit(train).calibrate(validation)


def test_parameters_and_comparator_status_are_frozen() -> None:
    baseline = HGBRCQRBaseline()

    assert baseline.status == BASELINE_STATUS == "HGBR_CQR_REPAIRED_FOR_LEAKAGE"
    assert baseline.config.targets == TARGETS
    assert baseline.config.horizons_hours == (6, 24, 72)
    assert "surge_flag" not in baseline.feature_names
    assert baseline.parameter_report()["optimization_or_grid_search"] is False
    with pytest.raises(ValueError, match="optimization is forbidden"):
        FrozenHGBRCQRConfig(max_iter=65)


def test_fit_and_calibration_splits_remain_strictly_isolated(
    fitted: HGBRCQRBaseline,
    splits: tuple[tuple[ForecastExample, ...], ...],
) -> None:
    train, validation, _ = splits
    training_hash = fitted.training_data_hash
    fill_values = fitted.training_fill_values

    assert fitted.train_row_ids == frozenset(row.row_id for row in train)
    assert fitted.calibration_row_ids == frozenset(row.row_id for row in validation)
    assert fitted.train_episode_ids == frozenset(row.episode_id for row in train)
    assert fitted.calibration_episode_ids == frozenset(row.episode_id for row in validation)
    assert fitted.training_data_hash == training_hash
    assert fitted.training_fill_values == fill_values
    with pytest.raises(ValueError, match="train/calibration row overlap"):
        fitted.calibrate(train[:2])
    same_episode_new_row = replace(train[0], row_id="different-row-same-train-episode")
    with pytest.raises(ValueError, match="train/calibration episode overlap"):
        fitted.calibrate((same_episode_new_row,))


def test_future_suffix_and_test_labels_cannot_change_prediction(
    fitted: HGBRCQRBaseline,
    splits: tuple[tuple[ForecastExample, ...], ...],
) -> None:
    _, _, test = splits
    original = test[0]
    future = TrajectoryPoint(
        record_id="future-suffix",
        observed_at=original.origin_at + timedelta(hours=3),
        available_at=original.origin_at + timedelta(hours=4),
        values=dict.fromkeys(TARGETS, 999_999.0),
    )
    corrupted_targets = {
        target: dict.fromkeys(HORIZONS_HOURS, 888_888.0) for target in TARGETS
    }
    modified = replace(
        original,
        history=(*original.history, future),
        future_targets=corrupted_targets,
    )

    before = fitted.predict((original,))
    after = fitted.predict((modified,))

    assert before == after


def test_forbidden_target_derived_feature_fails_closed(
    fitted: HGBRCQRBaseline,
    splits: tuple[tuple[ForecastExample, ...], ...],
) -> None:
    _, _, test = splits
    original = test[1]
    contaminated = replace(
        original,
        history=(
            *original.history,
            TrajectoryPoint(
                record_id="contaminated",
                observed_at=original.origin_at,
                available_at=original.origin_at,
                values={"surge_flag": 1.0},
            ),
        ),
    )

    with pytest.raises(ValueError, match="forbidden feature"):
        fitted.predict((contaminated,))


def test_quantiles_and_cqr_intervals_are_monotone(
    fitted: HGBRCQRBaseline,
    splits: tuple[tuple[ForecastExample, ...], ...],
) -> None:
    _, _, test = splits
    predictions = fitted.predict(test)

    assert len(predictions) == len(test) * len(TARGETS) * len(HORIZONS_HOURS)
    assert all(
        0.0 <= row.interval_low <= row.q_low <= row.q_median <= row.q_high <= row.interval_high
        for row in predictions
    )
    assert {row.target for row in predictions} == set(TARGETS)
    assert {row.horizon_hours for row in predictions} == set(HORIZONS_HOURS)
    assert {row.status for row in predictions} == {BASELINE_STATUS}


def test_validation_changes_only_cqr_width_not_quantile_models(
    fitted: HGBRCQRBaseline,
    splits: tuple[tuple[ForecastExample, ...], ...],
) -> None:
    _, validation, test = splits
    ordinary = fitted
    extreme_validation = tuple(
        replace(
            row,
            row_id=f"extreme-{row.row_id}",
            future_targets={
                target: dict.fromkeys(HORIZONS_HOURS, 1_000_000.0)
                for target in TARGETS
            },
        )
        for row in validation
    )
    widened = copy.deepcopy(fitted).calibrate(extreme_validation)

    ordinary_predictions = ordinary.predict(test)
    widened_predictions = widened.predict(test)
    assert [
        (row.q_low, row.q_median, row.q_high) for row in ordinary_predictions
    ] == [
        (row.q_low, row.q_median, row.q_high) for row in widened_predictions
    ]
    assert all(
        wide.interval_high - wide.interval_low
        >= normal.interval_high - normal.interval_low
        for normal, wide in zip(ordinary_predictions, widened_predictions, strict=True)
    )
    assert any(
        wide.interval_high - wide.interval_low
        > normal.interval_high - normal.interval_low
        for normal, wide in zip(ordinary_predictions, widened_predictions, strict=True)
    )


def test_fixed_seed_fit_is_deterministic(
    fitted: HGBRCQRBaseline,
    splits: tuple[tuple[ForecastExample, ...], ...],
) -> None:
    train, validation, test = splits
    second = HGBRCQRBaseline().fit(train).calibrate(validation)

    assert fitted.identity == second.identity
    assert fitted.training_data_hash == second.training_data_hash
    assert fitted.calibration_data_hash == second.calibration_data_hash
    assert fitted.predict(test) == second.predict(test)
