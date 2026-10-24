"""Censor-aware residual-preparation experiment, offline and synthetic only.

No total length-of-stay target is silently reused as a preparation duration.
HGB is a discrete-hazard challenger to a smoothed pooled hazard baseline.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from importlib.metadata import version
from typing import Annotated, Any, Literal, Self, cast

from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator
from sklearn.ensemble import HistGradientBoostingClassifier  # type: ignore[import-untyped]
from threadpoolctl import threadpool_limits  # type: ignore[import-untyped]

from hospitalos.operational.contract import Closed, Identifier, instant

from .models import State
from .preparation import (
    EDGES,
    PreparationCurve,
    PreparationFeatures,
    PreparationForecasts,
    eligible_patients,
    features_at,
)

CONFIG = {
    "max_iter": 60,
    "max_leaf_nodes": 7,
    "min_samples_leaf": 20,
    "learning_rate": 0.08,
    "l2_regularization": 1.0,
    "early_stopping": False,
    "random_state": 11,
}


class PreparationRecord(Closed):
    target: Literal["residual_preparation_before_resource_queue"] = (
        "residual_preparation_before_resource_queue"
    )
    provenance: Literal["synthetic_experiment"] = "synthetic_experiment"
    episode_id: Identifier
    patient_id: Identifier
    hospital_id: Identifier
    unit_id: Identifier
    origin: datetime
    features_available_at: datetime
    features: PreparationFeatures
    followed_minutes: Annotated[StrictInt, Field(ge=1, le=1440)]
    event_observed: StrictBool
    label_available_at: datetime

    @field_validator("origin", "features_available_at", "label_available_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return instant(value)

    @model_validator(mode="after")
    def information_boundaries(self) -> Self:
        if self.features_available_at > self.origin:
            raise ValueError("Feature unavailable at origin")
        if self.label_available_at < self.origin + timedelta(minutes=self.followed_minutes):
            raise ValueError("Outcome label cannot precede its follow-up")
        if (
            self.features.hour_utc != self.origin.hour
            or self.features.weekday_utc != self.origin.weekday()
        ):
            raise ValueError("Calendar features must match the UTC origin")
        return self


class Window(Closed):
    start: datetime
    end: datetime
    labels_available_by: datetime

    @field_validator("start", "end", "labels_available_by")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return instant(value)

    @model_validator(mode="after")
    def order(self) -> Self:
        if not self.start < self.end or self.labels_available_by < self.end + timedelta(
            minutes=1440
        ):
            raise ValueError("Each origin window requires a full 24h follow-up embargo")
        return self


class TemporalProtocol(Closed):
    train: Window
    calibration: Window
    validation: Window
    test: Window

    @model_validator(mode="after")
    def separated(self) -> Self:
        windows = (self.train, self.calibration, self.validation, self.test)
        if any(
            a.labels_available_by > b.start for a, b in zip(windows[:-1], windows[1:], strict=True)
        ):
            raise ValueError("Temporal windows or their label embargoes overlap")
        return self


@dataclass(frozen=True)
class Partitions:
    train: tuple[PreparationRecord, ...]
    calibration: tuple[PreparationRecord, ...]
    validation: tuple[PreparationRecord, ...]
    test: tuple[PreparationRecord, ...]


def partition(records: tuple[PreparationRecord, ...], protocol: TemporalProtocol) -> Partitions:
    if len({r.episode_id for r in records}) != len(records):
        raise ValueError("Duplicate episodes")
    groups: dict[tuple[str, str], str] = {}
    batches: dict[str, list[PreparationRecord]] = {
        k: [] for k in ("train", "calibration", "validation", "test")
    }
    for r in records:
        names = [
            k for k in batches if getattr(protocol, k).start <= r.origin < getattr(protocol, k).end
        ]
        if len(names) != 1:
            raise ValueError("Origin outside predeclared windows; do not silently repartition")
        name = names[0]
        if r.label_available_at > getattr(protocol, name).labels_available_by:
            raise ValueError("Label unavailable at this partition's cutoff")
        patient = (r.hospital_id, r.patient_id)
        if patient in groups:
            raise ValueError(
                "One origin per patient; repeated landmarks or partition overlap rejected"
            )
        groups[patient] = name
        batches[name].append(r)
    if any(not v for v in batches.values()):
        raise ValueError("All four chronological partitions must be nonempty")
    return Partitions(
        *(tuple(sorted(batches[k], key=lambda r: (r.origin, r.episode_id))) for k in batches)
    )


def observed_cells(record: PreparationRecord) -> tuple[tuple[int, int], ...]:
    """An event enters its enclosing bin; censored partial intervals contribute nothing."""
    labels = []
    for index, edge in enumerate(EDGES):
        if record.event_observed and record.followed_minutes <= edge:
            labels.append((index, 1))
            break
        if record.followed_minutes >= edge:
            labels.append((index, 0))
        else:
            break
    return tuple(labels)


def shifted(probability: float, offset: float) -> float:
    p = min(1 - 1e-8, max(1e-8, probability))
    return 1 / (1 + math.exp(-(math.log(p / (1 - p)) + offset)))


@dataclass(frozen=True)
class HazardModel:
    name: str
    pooled: tuple[float, ...]
    estimator: Any
    offset: float
    model_id: str
    available_at: datetime
    sites_units: frozenset[tuple[str, str]]
    feature_bounds: tuple[tuple[float, float], ...]

    def raw(self, features: tuple[PreparationFeatures, ...]) -> tuple[tuple[float, ...], ...]:
        if self.estimator is None:
            return tuple(self.pooled for _ in features)
        matrix = [[*f.vector(), float(index)] for f in features for index in range(len(EDGES))]
        with threadpool_limits(limits=1):
            probabilities = cast(list[list[float]], self.estimator.predict_proba(matrix).tolist())
        return tuple(
            tuple(float(probabilities[i * len(EDGES) + j][1]) for j in range(len(EDGES)))
            for i in range(len(features))
        )

    def hazards(self, features: tuple[PreparationFeatures, ...]) -> tuple[tuple[float, ...], ...]:
        return tuple(tuple(shifted(p, self.offset) for p in curve) for curve in self.raw(features))


def censored_nll(
    records: tuple[PreparationRecord, ...], hazards: tuple[tuple[float, ...], ...]
) -> float:
    if not records or len(records) != len(hazards):
        raise ValueError("Prediction/record size mismatch")
    return -sum(
        math.log(max(1e-12, curve[j] if outcome else 1 - curve[j]))
        for r, curve in zip(records, hazards, strict=True)
        for j, outcome in observed_cells(r)
    ) / len(records)


def fit_candidates(
    train: tuple[PreparationRecord, ...], available_at: datetime
) -> tuple[HazardModel, ...]:
    if any(r.label_available_at > available_at for r in train):
        raise ValueError("Training cannot read later labels")
    risk, events = [0] * len(EDGES), [0] * len(EDGES)
    matrix, labels = [], []
    for r in train:
        for index, outcome in observed_cells(r):
            risk[index] += 1
            events[index] += outcome
            matrix.append([*r.features.vector(), float(index)])
            labels.append(outcome)
    if not all(risk) or set(labels) != {0, 1}:
        raise ValueError("Training must support every interval and both event outcomes")
    pooled = tuple((d + 0.5) / (n + 1) for n, d in zip(risk, events, strict=True))
    estimator = HistGradientBoostingClassifier(**CONFIG)
    with threadpool_limits(limits=1):
        estimator.fit(matrix, labels)
    vectors = [r.features.vector() for r in train]
    bounds = tuple((min(v[j] for v in vectors), max(v[j] for v in vectors)) for j in range(2))
    sites = frozenset((r.hospital_id, r.unit_id) for r in train)
    return tuple(
        HazardModel(name, pooled, fitted, 0, "", available_at, sites, bounds)
        for name, fitted in (("pooled_hazard", None), ("gbm_hazard", estimator))
    )


def calibrate(
    model: HazardModel, records: tuple[PreparationRecord, ...], available_at: datetime
) -> HazardModel:
    if any(r.origin < model.available_at or r.label_available_at > available_at for r in records):
        raise ValueError("Calibration label/origin boundary violated")
    raw = model.raw(tuple(r.features for r in records))
    offsets = tuple(i / 10 for i in range(-20, 21))
    offset = min(
        offsets,
        key=lambda x: (
            censored_nll(records, tuple(tuple(shifted(p, x) for p in curve) for curve in raw)),
            abs(x),
            x,
        ),
    )
    return replace(model, offset=offset, available_at=available_at)


@dataclass(frozen=True)
class CensoringDistribution:
    # Reverse KM: observed events are removed before censoring at a tied time.
    steps: tuple[tuple[int, float], ...]
    max_followup: int

    def survival(self, minute: int, *, before: bool = False) -> float:
        if minute > self.max_followup:
            raise ValueError("Censoring support exhausted")
        result = 1.0
        for time, probability in self.steps:
            if time < minute or (time == minute and not before):
                result = probability
        return result


def fit_censoring(train: tuple[PreparationRecord, ...]) -> CensoringDistribution:
    if not train:
        raise ValueError("Censoring estimator needs training follow-up")
    survival, steps = 1.0, []
    for time in sorted({r.followed_minutes for r in train}):
        at_risk = sum(r.followed_minutes >= time for r in train)
        failures = sum(r.followed_minutes == time and r.event_observed for r in train)
        censored = sum(r.followed_minutes == time and not r.event_observed for r in train)
        if censored:
            survival *= 1 - censored / (at_risk - failures)
        steps.append((time, survival))
    return CensoringDistribution(tuple(steps), max(r.followed_minutes for r in train))


def survival_curve(hazards: tuple[float, ...]) -> tuple[float, ...]:
    value, result = 1.0, []
    for hazard in hazards:
        value *= 1 - hazard
        result.append(value)
    return tuple(result)


def brier_at(
    records: tuple[PreparationRecord, ...],
    survival: tuple[float, ...],
    horizon: int,
    censoring: CensoringDistribution,
) -> dict[str, float | str | None]:
    if len(records) != len(survival) or not records:
        raise ValueError("Prediction/record size mismatch")
    if horizon > censoring.max_followup:
        return {
            "brier_ipcw": None,
            "observed_event_rate_ipcw": None,
            "reason": "insufficient_censoring_support",
        }
    g = censoring.survival(horizon)
    if g < 0.1:
        return {
            "brier_ipcw": None,
            "observed_event_rate_ipcw": None,
            "reason": "insufficient_censoring_support",
        }
    loss, event_rate = 0.0, 0.0
    for r, estimate in zip(records, survival, strict=True):
        if r.event_observed and r.followed_minutes <= horizon:
            weight = censoring.survival(r.followed_minutes, before=True)
            if weight < 0.1:
                return {
                    "brier_ipcw": None,
                    "observed_event_rate_ipcw": None,
                    "reason": "insufficient_censoring_support",
                }
            loss += estimate**2 / weight
            event_rate += 1 / weight
        elif r.followed_minutes > horizon:
            loss += (1 - estimate) ** 2 / g
    return {
        "brier_ipcw": loss / len(records),
        "observed_event_rate_ipcw": event_rate / len(records),
        "reason": None,
    }


def evaluate(
    model: HazardModel, records: tuple[PreparationRecord, ...], censoring: CensoringDistribution
) -> dict[str, Any]:
    if any(r.origin < model.available_at for r in records):
        raise ValueError("Evaluation would use a model unavailable at origin")
    hazards = model.hazards(tuple(r.features for r in records))
    curves = tuple(survival_curve(h) for h in hazards)
    horizons = {}
    for minute in (60, 120, 240, 480):
        index = EDGES.index(minute)
        predicted = tuple(s[index] for s in curves)
        horizons[str(minute)] = {
            **brier_at(records, predicted, minute, censoring),
            "predicted_event_rate": statistics.mean(1 - s for s in predicted),
        }
    return {
        "records": len(records),
        "events": sum(r.event_observed for r in records),
        "censored": sum(not r.event_observed for r in records),
        "informative_records": sum(bool(observed_cells(r)) for r in records),
        "interval_nll_per_record": censored_nll(records, hazards),
        "horizons_minutes": horizons,
    }


@dataclass(frozen=True)
class Selection:
    selected: HazardModel
    candidates: tuple[HazardModel, ...]
    censoring: CensoringDistribution
    validation: dict[str, dict[str, Any]]


def select_model(
    train: tuple[PreparationRecord, ...],
    calibration: tuple[PreparationRecord, ...],
    validation: tuple[PreparationRecord, ...],
    protocol: TemporalProtocol,
) -> Selection:
    # No test-set argument: selection and model identity cannot read its outcomes.
    episodes: set[str] = set()
    patients: set[tuple[str, str]] = set()
    for name, records in (
        ("train", train),
        ("calibration", calibration),
        ("validation", validation),
    ):
        window = getattr(protocol, name)
        if not records:
            raise ValueError("Each selection partition must be nonempty")
        if not any(observed_cells(r) for r in records):
            raise ValueError("Each selection partition needs observed interval information")
        for r in records:
            if (
                not window.start <= r.origin < window.end
                or r.label_available_at > window.labels_available_by
            ):
                raise ValueError("Record outside its declared selection partition/cutoff")
            if r.episode_id in episodes or (r.hospital_id, r.patient_id) in patients:
                raise ValueError("Duplicate episode or patient across selection partitions")
            episodes.add(r.episode_id)
            patients.add((r.hospital_id, r.patient_id))
    train, calibration, validation = (
        tuple(sorted(batch, key=lambda r: (r.origin, r.episode_id)))
        for batch in (train, calibration, validation)
    )
    candidates = tuple(
        calibrate(m, calibration, protocol.calibration.labels_available_by)
        for m in fit_candidates(train, protocol.train.labels_available_by)
    )
    censoring = fit_censoring(train)
    validation_scores = {m.name: evaluate(m, validation, censoring) for m in candidates}
    selected_name = min(
        validation_scores,
        key=lambda name: (
            validation_scores[name]["interval_nll_per_record"],
            name != "pooled_hazard",
        ),
    )
    data_hash = hashlib.sha256(
        "\n".join(sorted(r.model_dump_json() for r in train + calibration + validation)).encode()
    ).hexdigest()
    final = []
    for m in candidates:
        identity = hashlib.sha256(
            json.dumps(
                {
                    "schema": "preparation-hazard-v1",
                    "data": data_hash,
                    "protocol": protocol.model_dump(mode="json", exclude={"test"}),
                    "config": CONFIG,
                    "algorithm": m.name,
                    "offset": m.offset,
                    "sklearn": version("scikit-learn"),
                    "edges": EDGES,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        final.append(
            replace(m, model_id=identity, available_at=protocol.validation.labels_available_by)
        )
    return Selection(
        next(m for m in final if m.name == selected_name),
        tuple(final),
        censoring,
        validation_scores,
    )


def forecast_preparation(model: HazardModel, state: State) -> PreparationForecasts:
    if state.issues or model.available_at > state.at:
        raise ValueError("Model/state not available for this prediction")
    ids = eligible_patients(state)
    features = tuple(features_at(state, pid) for pid in ids)
    for pid, f in zip(ids, features, strict=True):
        patient = next(p for p in state.patients if p.id == pid)
        bed = next(b for b in state.beds if b.id == patient.bed_id)
        if (state.hospital_id, bed.unit_id) not in model.sites_units or any(
            not low <= value <= high
            for value, (low, high) in zip(f.vector()[:2], model.feature_bounds, strict=True)
        ):
            raise ValueError("Prediction outside the fitted site/unit or load support")
    hazards = model.hazards(features) if features else ()
    curves = []
    for pid, h in zip(ids, hazards, strict=True):
        remaining, mass = 1.0, []
        for probability in h:
            mass.append(remaining * probability)
            remaining *= 1 - probability
        curves.append(PreparationCurve(patient_id=pid, mass=tuple(mass), beyond_24h=remaining))
    return PreparationForecasts(
        model_id=model.model_id,
        hospital_id=state.hospital_id,
        state_fingerprint=state.fingerprint,
        origin=state.at,
        model_available_at=model.available_at,
        curves=tuple(curves),
    )
