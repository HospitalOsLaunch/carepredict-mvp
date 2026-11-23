"""Locked continuous synthetic cohorts and pooled/logistic/boosting estimators."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from typing import Any, cast
from zoneinfo import ZoneInfo

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier  # type: ignore[import-untyped]
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from threadpoolctl import threadpool_limits  # type: ignore[import-untyped]

from .continuous import GRID, Array, coupled_ranks, log_loss, quantiles, rates_from_hazards

PARIS = ZoneInfo("Europe/Paris")
FIT_AVAILABLE = datetime(2026, 8, 1, tzinfo=UTC)
WEIGHT_AVAILABLE = datetime(2026, 8, 15, tzinfo=UTC)
LOCK = datetime(2026, 12, 1, tzinfo=UTC)
TEST_START = datetime(2027, 1, 1, tzinfo=UTC)
LOADING = 0.6


def calendar(at: datetime) -> tuple[float, float, float]:
    if at.tzinfo is None:
        raise ValueError("UTC-aware origin required")
    local = at.astimezone(PARIS)
    angle = 2 * np.pi * (local.hour + local.minute / 60) / 24
    return float(np.sin(angle)), float(np.cos(angle)), float(local.weekday() >= 5)


@dataclass(frozen=True)
class Cohort:
    features: Array
    time: Array
    observed: Array
    truth: Array
    origin: datetime
    episodes: int
    seed: int

    @property
    def last_label_at(self) -> datetime:
        return self.origin + timedelta(hours=2 * (self.episodes - 1) + 24)


def context_features(seed: int, episodes: int, origin: datetime) -> Array:
    rng = np.random.default_rng(seed)
    load = rng.uniform(0.3, 1.5, (episodes, 3))
    waiting = rng.uniform(0, 1.5, (episodes, 3))
    dates = np.array([calendar(origin + timedelta(hours=2 * i)) for i in range(episodes)])
    return cast(
        Array,
        np.concatenate(
            (load[..., None], waiting[..., None], np.repeat(dates[:, None], 3, axis=1)), axis=2
        ).reshape(-1, 5),
    )


def truth_rates(features: Array, coefficient: float | Array = -2.0, shift: float = 0) -> Array:
    # Exactly linear logistic patient-interval hazards; continuous exponential
    # interpolation inside each interval. The final interval has its own width.
    coefficient = np.asarray(coefficient)
    base = (
        -2.0
        + coefficient * (features[:, 0] - 0.8)
        - 0.7 * features[:, 1]
        + 0.3 * features[:, 2]
        + shift
    )
    logit = base[:, None] + 0.06 * np.arange(len(GRID))
    return rates_from_hazards(1 / (1 + np.exp(-logit)))


def cohort(
    seed: int,
    episodes: int,
    origin: datetime,
    coefficient: float | Array = -2.0,
    shift: float = 0,
    loading: float = LOADING,
) -> Cohort:
    f = context_features(seed, episodes, origin)
    rng = np.random.default_rng(seed + 1000000)
    common = rng.uniform(1e-12, 1 - 1e-12, (episodes, 1))
    individual = rng.uniform(1e-12, 1 - 1e-12, (episodes, 3))
    u = coupled_ranks(common, individual, loading).reshape(-1, 1)
    truth = quantiles(truth_rates(f, coefficient, shift), u)[:, 0]
    censor = np.random.default_rng(seed + 2000000).choice((180, 300, 480, 1440, 1440), len(f))
    return Cohort(f, np.minimum(truth, censor), truth <= censor, truth, origin, episodes, seed)


@dataclass(frozen=True)
class Experts:
    pooled: Array
    logistic: Any
    boosting: Any
    identity: str
    available_at: datetime

    def predict(self, features: Array) -> dict[str, Array]:
        # Limits protect against accidental giant matrices in alarm simulation.
        result: dict[str, list[Array]] = {k: [] for k in ("pooled", "logistic", "boosting")}
        with threadpool_limits(limits=1):
            for first in range(0, len(features), 3000):
                f = features[first : first + 3000]
                matrix = np.c_[
                    np.repeat(f, len(GRID), axis=0), np.tile(np.arange(len(GRID)), len(f))
                ]
                result["pooled"].append(np.repeat(self.pooled[None], len(f), axis=0))
                for name, model in (("logistic", self.logistic), ("boosting", self.boosting)):
                    hazards = model.predict_proba(matrix)[:, 1].reshape(len(f), len(GRID))
                    result[name].append(rates_from_hazards(np.clip(hazards, 1e-8, 1 - 1e-8)))
        return {k: np.concatenate(v) for k, v in result.items()}


def fit_experts(data: Cohort, available_at: datetime = FIT_AVAILABLE) -> Experts:
    if data.last_label_at > available_at:
        raise ValueError("Future training labels")
    index = np.searchsorted(GRID, data.time, side="left")
    cells = np.arange(len(GRID))[None, :]
    positive = data.observed[:, None] & (cells == index[:, None])
    observed = (GRID[None, :] <= data.time[:, None]) | positive
    matrix = np.c_[
        np.repeat(data.features, len(GRID), axis=0),
        np.tile(np.arange(len(GRID)), len(data.features)),
    ][observed.ravel()]
    labels = positive[observed].astype(int)
    risk = observed.sum(axis=0)
    if np.any(risk == 0) or len(np.unique(labels)) != 2:
        raise ValueError("Insufficient interval support")
    pooled = rates_from_hazards((positive.sum(axis=0) + 0.5) / (risk + 1))
    logistic = LogisticRegression(C=100, max_iter=500, tol=1e-8)
    boosting = HistGradientBoostingClassifier(
        max_iter=60,
        max_leaf_nodes=7,
        min_samples_leaf=30,
        learning_rate=0.08,
        l2_regularization=1,
        early_stopping=False,
        random_state=71,
    )
    with threadpool_limits(limits=1):
        logistic.fit(matrix, labels)
        boosting.fit(matrix, labels)
    identity = hashlib.sha256(
        matrix.tobytes()
        + labels.tobytes()
        + json.dumps(
            {
                "version": "continuous-v2",
                "sklearn": version("scikit-learn"),
                "logistic": logistic.get_params(),
                "boosting": boosting.get_params(),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return Experts(pooled, logistic, boosting, identity, available_at)


def select_weight(experts: Experts, data: Cohort) -> tuple[float, dict[str, float]]:
    if data.origin < experts.available_at or data.last_label_at > WEIGHT_AVAILABLE:
        raise ValueError("Weight-selection information boundary")
    prediction = experts.predict(data.features)
    scores = {
        str(a): float(
            np.mean(
                log_loss(prediction["pooled"], data.time, data.observed, prediction["boosting"], a)
            )
        )
        for a in (0.0, 0.25, 0.5, 0.75, 1.0)
    }
    return min((float(a) for a in scores), key=lambda a: (scores[str(a)], a)), scores
