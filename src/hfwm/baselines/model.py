"""Frozen HGBR/CQR final baseline repaired only for leakage and integrity.

Unlike the legacy ``carepredict_quantile.py`` pipeline, this comparator has no
target-derived ``surge_flag``, no hyperparameter search, and no split-local
imputation.  Feature construction is a pure point-in-time projection.  Quantile
models see train labels only; CQR sees validation labels only; test labels are not
read during prediction.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Final, TypeAlias, cast

import numpy as np
import numpy.typing as npt
from sklearn.ensemble import HistGradientBoostingRegressor  # type: ignore[import-untyped]

from hfwm.contracts import ComponentIdentity

FloatArray: TypeAlias = npt.NDArray[np.float64]

BASELINE_STATUS: Final = "HGBR_CQR_REPAIRED_FOR_LEAKAGE"
TARGETS: Final = ("occupancy", "inflow", "discharges", "staffing", "pressure")
HORIZONS_HOURS: Final = (6, 24, 72)
_QUANTILES: Final = (0.05, 0.50, 0.95)
_ALPHA: Final = 0.10
_SEED: Final = 1729
_MAX_ITER: Final = 64
_LEARNING_RATE: Final = 0.05
_L2_REGULARIZATION: Final = 0.01
_MAX_LEAF_NODES: Final = 15
_MIN_SAMPLES_LEAF: Final = 5
_MAX_BINS: Final = 64
_FORBIDDEN_FEATURE_KEYS: Final = frozenset(
    {"surge_flag", "target", "current_target", "future_target"}
)


@dataclass(frozen=True, slots=True)
class FrozenHGBRCQRConfig:
    """Closed pre-registered baseline parameters; alternatives are rejected."""

    targets: tuple[str, ...] = TARGETS
    horizons_hours: tuple[int, ...] = HORIZONS_HOURS
    quantiles: tuple[float, ...] = _QUANTILES
    alpha: float = _ALPHA
    seed: int = _SEED
    max_iter: int = _MAX_ITER
    learning_rate: float = _LEARNING_RATE
    l2_regularization: float = _L2_REGULARIZATION
    max_leaf_nodes: int = _MAX_LEAF_NODES
    min_samples_leaf: int = _MIN_SAMPLES_LEAF
    max_bins: int = _MAX_BINS
    early_stopping: bool = False

    def __post_init__(self) -> None:
        expected = (
            self.targets == TARGETS
            and self.horizons_hours == HORIZONS_HOURS
            and self.quantiles == _QUANTILES
            and self.alpha == _ALPHA
            and self.seed == _SEED
            and self.max_iter == _MAX_ITER
            and self.learning_rate == _LEARNING_RATE
            and self.l2_regularization == _L2_REGULARIZATION
            and self.max_leaf_nodes == _MAX_LEAF_NODES
            and self.min_samples_leaf == _MIN_SAMPLES_LEAF
            and self.max_bins == _MAX_BINS
            and self.early_stopping is False
        )
        if not expected:
            raise ValueError("HGBR/CQR parameters are frozen; optimization is forbidden")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def semantic_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class TrajectoryPoint:
    """One observation; only points visible at the forecast origin become features."""

    record_id: str
    observed_at: datetime
    available_at: datetime
    values: Mapping[str, float | None]

    def __post_init__(self) -> None:
        if not self.record_id:
            raise ValueError("trajectory point record_id must not be empty")
        _aware(self.observed_at, "observed_at")
        _aware(self.available_at, "available_at")


@dataclass(frozen=True, slots=True)
class ForecastExample:
    """One split-before-windowing HFWM trajectory and its held-out labels."""

    row_id: str
    episode_id: str
    site_id: str
    origin_at: datetime
    history: Sequence[TrajectoryPoint]
    future_targets: Mapping[str, Mapping[int, float | None]]

    def __post_init__(self) -> None:
        if not self.row_id or not self.episode_id or not self.site_id:
            raise ValueError("forecast example identifiers must not be empty")
        _aware(self.origin_at, "origin_at")


@dataclass(frozen=True, slots=True)
class BaselineSplits:
    train: tuple[ForecastExample, ...]
    validation: tuple[ForecastExample, ...]
    test: tuple[ForecastExample, ...]

    def __post_init__(self) -> None:
        groups = (
            {row.row_id for row in self.train},
            {row.row_id for row in self.validation},
            {row.row_id for row in self.test},
        )
        episode_groups = (
            {row.episode_id for row in self.train},
            {row.episode_id for row in self.validation},
            {row.episode_id for row in self.test},
        )
        if any(not group for group in groups):
            raise ValueError("train, validation and test splits must all be non-empty")
        if groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2]:
            raise ValueError("baseline row identities must be split-disjoint")
        if (
            episode_groups[0] & episode_groups[1]
            or episode_groups[0] & episode_groups[2]
            or episode_groups[1] & episode_groups[2]
        ):
            raise ValueError("baseline episode identities must be split-disjoint")


@dataclass(frozen=True, slots=True)
class BaselinePrediction:
    row_id: str
    site_id: str
    origin_at: datetime
    target: str
    horizon_hours: int
    q_low: float
    q_median: float
    q_high: float
    interval_low: float
    interval_high: float
    status: str = BASELINE_STATUS


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _visible_history(example: ForecastExample) -> tuple[TrajectoryPoint, ...]:
    """Return latest point-in-time corrections, excluding every future suffix."""

    by_observed_at: dict[datetime, TrajectoryPoint] = {}
    for point in example.history:
        if point.observed_at > example.origin_at or point.available_at > example.origin_at:
            continue
        lowered = {key.lower() for key in point.values}
        forbidden = sorted(
            key
            for key in lowered
            if key in _FORBIDDEN_FEATURE_KEYS
            or key.startswith("target_")
            or key.startswith("future_")
        )
        if forbidden:
            raise ValueError(f"target-derived or forbidden feature keys: {forbidden}")
        previous = by_observed_at.get(point.observed_at)
        if previous is None or (point.available_at, point.record_id) > (
            previous.available_at,
            previous.record_id,
        ):
            by_observed_at[point.observed_at] = point
    return tuple(
        by_observed_at[key]
        for key in sorted(by_observed_at)
    )


def _feature_names() -> tuple[str, ...]:
    temporal = ("origin_hour_sin", "origin_hour_cos", "origin_weekday_sin", "origin_weekday_cos")
    historical = tuple(
        f"{target}__{summary}"
        for target in TARGETS
        for summary in ("last", "lag2", "mean3", "delta")
    )
    return (*temporal, *historical)


FEATURE_NAMES: Final = _feature_names()


def _feature_row(example: ForecastExample) -> FloatArray:
    visible = _visible_history(example)
    origin = _aware(example.origin_at, "origin_at")
    hour_phase = 2.0 * math.pi * (origin.hour + origin.minute / 60.0) / 24.0
    weekday_phase = 2.0 * math.pi * origin.weekday() / 7.0
    features = [
        math.sin(hour_phase),
        math.cos(hour_phase),
        math.sin(weekday_phase),
        math.cos(weekday_phase),
    ]
    for target in TARGETS:
        values = [
            number
            for point in visible
            if (number := _finite(point.values.get(target))) is not None
        ]
        last = values[-1] if values else math.nan
        lag2 = values[-2] if len(values) >= 2 else math.nan
        mean3 = sum(values[-3:]) / len(values[-3:]) if values else math.nan
        delta = last - lag2 if math.isfinite(last) and math.isfinite(lag2) else math.nan
        features.extend((last, lag2, mean3, delta))
    return np.asarray(features, dtype=np.float64)


def _feature_matrix(examples: Sequence[ForecastExample]) -> FloatArray:
    if not examples:
        raise ValueError("baseline requires at least one example")
    row_ids = [example.row_id for example in examples]
    if len(row_ids) != len(set(row_ids)):
        raise ValueError("duplicate baseline row_id")
    return np.stack([_feature_row(example) for example in examples])


def _labels(
    examples: Sequence[ForecastExample],
    target: str,
    horizon: int,
) -> tuple[FloatArray, npt.NDArray[np.bool_]]:
    values: list[float] = []
    observed: list[bool] = []
    for example in examples:
        target_horizons = example.future_targets.get(target, {})
        number = _finite(target_horizons.get(horizon))
        values.append(number if number is not None else math.nan)
        observed.append(number is not None)
    return np.asarray(values, dtype=np.float64), np.asarray(observed, dtype=np.bool_)


def _higher_conformal_quantile(scores: FloatArray, alpha: float) -> float:
    if scores.size == 0:
        raise ValueError("CQR calibration requires observed validation targets")
    level = min(1.0, math.ceil((scores.size + 1) * (1.0 - alpha)) / scores.size)
    return max(0.0, float(np.quantile(scores, level, method="higher")))


def _examples_hash(examples: Sequence[ForecastExample], *, include_targets: bool) -> str:
    records: list[dict[str, object]] = []
    for example in sorted(examples, key=lambda item: item.row_id):
        record: dict[str, object] = {
            "episode_id": example.episode_id,
            "features": [
                float(value) if math.isfinite(value) else None
                for value in _feature_row(example)
            ],
            "origin_at": _aware(example.origin_at, "origin_at").isoformat(),
            "row_id": example.row_id,
            "site_id": example.site_id,
        }
        if include_targets:
            record["targets"] = {
                target: {
                    str(horizon): _finite(example.future_targets.get(target, {}).get(horizon))
                    for horizon in HORIZONS_HOURS
                }
                for target in TARGETS
            }
        records.append(record)
    payload = json.dumps(records, allow_nan=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class HGBRCQRBaseline:
    """Train-only quantile HGBR plus validation-only global CQR calibration."""

    status: Final = BASELINE_STATUS

    def __init__(self, config: FrozenHGBRCQRConfig | None = None) -> None:
        self.config = config or FrozenHGBRCQRConfig()
        self.identity = ComponentIdentity(
            component_type="ForecastBaseline",
            implementation_id="legacy_hgbr_cqr_leakage_repaired",
            contract_version="hfwm.baseline.v1",
            implementation_version="hfwm-r0.1",
            artifact_hash=self.config.semantic_hash(),
        )
        self._models: dict[tuple[str, int, float], HistGradientBoostingRegressor] = {}
        self._fill_values: FloatArray | None = None
        self._qhat: dict[tuple[str, int], float] = {}
        self._train_ids: frozenset[str] = frozenset()
        self._train_episode_ids: frozenset[str] = frozenset()
        self._calibration_ids: frozenset[str] = frozenset()
        self._calibration_episode_ids: frozenset[str] = frozenset()
        self._train_hash: str | None = None
        self._calibration_hash: str | None = None

    @property
    def feature_names(self) -> tuple[str, ...]:
        return FEATURE_NAMES

    @property
    def train_row_ids(self) -> frozenset[str]:
        return self._train_ids

    @property
    def calibration_row_ids(self) -> frozenset[str]:
        return self._calibration_ids

    @property
    def train_episode_ids(self) -> frozenset[str]:
        return self._train_episode_ids

    @property
    def calibration_episode_ids(self) -> frozenset[str]:
        return self._calibration_episode_ids

    @property
    def training_data_hash(self) -> str | None:
        return self._train_hash

    @property
    def calibration_data_hash(self) -> str | None:
        return self._calibration_hash

    @property
    def training_fill_values(self) -> tuple[float, ...]:
        if self._fill_values is None:
            raise RuntimeError("baseline has not been fitted")
        return tuple(float(value) for value in self._fill_values)

    def parameter_report(self) -> dict[str, object]:
        return {
            **self.config.to_dict(),
            "feature_names": list(self.feature_names),
            "model_count": len(self._models),
            "optimization_or_grid_search": False,
            "status": self.status,
        }

    def fit(self, train: Sequence[ForecastExample]) -> HGBRCQRBaseline:
        """Fit fixed quantile models using train features and labels only."""

        design = _feature_matrix(train)
        self._train_ids = frozenset(example.row_id for example in train)
        self._train_episode_ids = frozenset(example.episode_id for example in train)
        medians = np.zeros(design.shape[1], dtype=np.float64)
        for column in range(design.shape[1]):
            observed = design[np.isfinite(design[:, column]), column]
            medians[column] = float(np.median(observed)) if observed.size else 0.0
        self._fill_values = medians
        fitted_design = self._impute(design)
        models: dict[tuple[str, int, float], HistGradientBoostingRegressor] = {}
        for target in TARGETS:
            for horizon in HORIZONS_HOURS:
                labels, observed_mask = _labels(train, target, horizon)
                if int(observed_mask.sum()) < 2:
                    raise ValueError(
                        f"train lacks two observed labels for {target}@{horizon}h"
                    )
                for quantile in _QUANTILES:
                    model = HistGradientBoostingRegressor(
                        loss="quantile",
                        quantile=quantile,
                        max_iter=self.config.max_iter,
                        learning_rate=self.config.learning_rate,
                        l2_regularization=self.config.l2_regularization,
                        max_leaf_nodes=self.config.max_leaf_nodes,
                        min_samples_leaf=self.config.min_samples_leaf,
                        max_bins=self.config.max_bins,
                        early_stopping=self.config.early_stopping,
                        random_state=self.config.seed,
                    )
                    model.fit(fitted_design[observed_mask], labels[observed_mask])
                    models[(target, horizon, quantile)] = model
        self._models = models
        self._qhat.clear()
        self._calibration_ids = frozenset()
        self._calibration_episode_ids = frozenset()
        self._calibration_hash = None
        self._train_hash = _examples_hash(train, include_targets=True)
        self._refresh_identity()
        return self

    def calibrate(self, validation: Sequence[ForecastExample]) -> HGBRCQRBaseline:
        """Calibrate CQR widths with validation labels, without refitting HGBR."""

        self._require_fitted()
        validation_ids = frozenset(example.row_id for example in validation)
        validation_episode_ids = frozenset(example.episode_id for example in validation)
        overlap = self._train_ids & validation_ids
        if overlap:
            raise ValueError(f"train/calibration row overlap: {sorted(overlap)}")
        episode_overlap = self._train_episode_ids & validation_episode_ids
        if episode_overlap:
            raise ValueError(
                f"train/calibration episode overlap: {sorted(episode_overlap)}"
            )
        quantiles = self._raw_quantiles(validation)
        qhat: dict[tuple[str, int], float] = {}
        for target in TARGETS:
            for horizon in HORIZONS_HOURS:
                labels, observed_mask = _labels(validation, target, horizon)
                if not observed_mask.any():
                    raise ValueError(
                        f"validation lacks observed labels for {target}@{horizon}h"
                    )
                low, _, high = quantiles[(target, horizon)]
                scores = np.maximum(
                    low[observed_mask] - labels[observed_mask],
                    labels[observed_mask] - high[observed_mask],
                )
                qhat[(target, horizon)] = _higher_conformal_quantile(
                    cast(FloatArray, scores),
                    self.config.alpha,
                )
        self._qhat = qhat
        self._calibration_ids = validation_ids
        self._calibration_episode_ids = validation_episode_ids
        self._calibration_hash = _examples_hash(validation, include_targets=True)
        self._refresh_identity()
        return self

    def predict(self, examples: Sequence[ForecastExample]) -> tuple[BaselinePrediction, ...]:
        """Evaluate features only; supplied test targets are deliberately ignored."""

        if not self._qhat:
            raise RuntimeError("baseline must be calibrated before interval prediction")
        evaluation_ids = {example.row_id for example in examples}
        evaluation_episode_ids = {example.episode_id for example in examples}
        overlap = evaluation_ids & (self._train_ids | self._calibration_ids)
        if overlap:
            raise ValueError(f"evaluation rows overlap fit/calibration: {sorted(overlap)}")
        episode_overlap = evaluation_episode_ids & (
            self._train_episode_ids | self._calibration_episode_ids
        )
        if episode_overlap:
            raise ValueError(
                f"evaluation episodes overlap fit/calibration: {sorted(episode_overlap)}"
            )
        quantiles = self._raw_quantiles(examples)
        predictions: list[BaselinePrediction] = []
        for row_index, example in enumerate(examples):
            for target in TARGETS:
                for horizon in HORIZONS_HOURS:
                    low, median, high = quantiles[(target, horizon)]
                    qhat = self._qhat[(target, horizon)]
                    predictions.append(
                        BaselinePrediction(
                            row_id=example.row_id,
                            site_id=example.site_id,
                            origin_at=example.origin_at,
                            target=target,
                            horizon_hours=horizon,
                            q_low=max(0.0, float(low[row_index])),
                            q_median=max(0.0, float(median[row_index])),
                            q_high=max(0.0, float(high[row_index])),
                            interval_low=max(0.0, float(low[row_index]) - qhat),
                            interval_high=max(0.0, float(high[row_index]) + qhat),
                        )
                    )
        return tuple(predictions)

    def _raw_quantiles(
        self,
        examples: Sequence[ForecastExample],
    ) -> dict[tuple[str, int], tuple[FloatArray, FloatArray, FloatArray]]:
        self._require_fitted()
        design = self._impute(_feature_matrix(examples))
        result: dict[tuple[str, int], tuple[FloatArray, FloatArray, FloatArray]] = {}
        for target in TARGETS:
            for horizon in HORIZONS_HOURS:
                raw = np.column_stack(
                    [
                        self._models[(target, horizon, quantile)].predict(design)
                        for quantile in _QUANTILES
                    ]
                )
                ordered = np.sort(raw, axis=1)
                result[(target, horizon)] = (
                    cast(FloatArray, ordered[:, 0]),
                    cast(FloatArray, ordered[:, 1]),
                    cast(FloatArray, ordered[:, 2]),
                )
        return result

    def _impute(self, design: FloatArray) -> FloatArray:
        if self._fill_values is None:
            raise RuntimeError("training medians are unavailable before fit")
        return cast(FloatArray, np.where(np.isfinite(design), design, self._fill_values))

    def _require_fitted(self) -> None:
        if len(self._models) != len(TARGETS) * len(HORIZONS_HOURS) * len(_QUANTILES):
            raise RuntimeError("baseline has not been fitted")

    def _refresh_identity(self) -> None:
        parts = [self.config.semantic_hash(), self._train_hash or "UNFITTED"]
        if self._calibration_hash is not None:
            parts.extend(
                (
                    self._calibration_hash,
                    json.dumps(
                        {
                            f"{target}@{horizon}": self._qhat[(target, horizon)]
                            for target in TARGETS
                            for horizon in HORIZONS_HOURS
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                )
            )
        artifact_hash = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()
        self.identity = ComponentIdentity(
            component_type="ForecastBaseline",
            implementation_id="legacy_hgbr_cqr_leakage_repaired",
            contract_version="hfwm.baseline.v1",
            implementation_version="hfwm-r0.1",
            artifact_hash=artifact_hash,
        )
