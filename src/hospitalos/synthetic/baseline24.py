"""A frozen persistence reference, isolated from future labels and simulator truth."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from .asof import AsOfRow

HORIZON_H = 24
TARGET_UNITS = {
    "lits_occupes": "beds",
    "attente_urgences_nb": "patients",
    "charge_soins_min_h": "care_minutes_per_hour",
}


def predict(rows: Iterable[AsOfRow]) -> list[dict[str, Any]]:
    """Persist the latest available state; abstain on missing or stale observations."""
    predictions = []
    for row in rows:
        reason = "missing" if row.missing else ("stale" if row.stale else "available")
        predictions.append(
            {
                "sample_id": row.sample_id,
                "entity_id": row.entity_id,
                "level": row.level,
                "hospital_id": row.hospital_id,
                "partition": row.partition,
                "decision_h": row.decision_h,
                "target_h": row.decision_h + HORIZON_H,
                "horizon_h": HORIZON_H,
                "method": "persistence_24h",
                "status": reason,
                **{
                    f"prediction_{name}": float(getattr(row.values, name))
                    if reason == "available" and row.values is not None
                    else None
                    for name in TARGET_UNITS
                },
            }
        )
    return predictions


def score(
    predictions: list[dict[str, Any]],
    labels: list[dict[str, Any]],
) -> dict[str, Any]:
    """Report errors and coverage by entity, never pool the three hierarchy levels."""
    truth = {row["sample_id"]: row for row in labels}
    if len(truth) != len(labels) or len({row["sample_id"] for row in predictions}) != len(
        predictions
    ):
        raise ValueError("Duplicate scoring sample")
    if set(truth) != {row["sample_id"] for row in predictions}:
        raise ValueError("Prediction/label sample mismatch")
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for prediction in predictions:
        label = truth[prediction["sample_id"]]
        for field in ("entity_id", "level", "hospital_id", "partition", "decision_h", "target_h"):
            if prediction[field] != label[field]:
                raise ValueError(f"Prediction/label {field} mismatch")
        if (
            prediction["target_h"] != prediction["decision_h"] + HORIZON_H
            or prediction["horizon_h"] != HORIZON_H
            or label["horizon_h"] != HORIZON_H
        ):
            raise ValueError("Incorrect forecast horizon")
        for name, unit in TARGET_UNITS.items():
            key = (prediction["level"], prediction["entity_id"], name)
            group = groups.setdefault(
                key,
                {
                    "level": key[0],
                    "entity_id": key[1],
                    "target": name,
                    "unit": unit,
                    "total": 0,
                    "censored": 0,
                    "missing": 0,
                    "stale": 0,
                    "eligible": 0,
                    "errors": [],
                },
            )
            group["total"] += 1
            target = label[f"target_{name}"]
            if label["censored"]:
                if target is not None:
                    raise ValueError("Censored target must be null")
                group["censored"] += 1
                continue
            if target is None or not math.isfinite(float(target)):
                raise ValueError("Eligible target must be finite")
            group["eligible"] += 1
            value = prediction[f"prediction_{name}"]
            if prediction["status"] in ("missing", "stale"):
                if value is not None:
                    raise ValueError("Abstention cannot have a prediction")
                group[prediction["status"]] += 1
                continue
            if prediction["status"] != "available" or value is None or not math.isfinite(value):
                raise ValueError("Available prediction must be finite")
            group["errors"].append(value - target)
    metrics = []
    for key in sorted(groups):
        group = groups[key]
        errors = group.pop("errors")
        count = len(errors)
        metrics.append(
            {
                **group,
                "n_scored": count,
                "coverage": count / group["eligible"] if group["eligible"] else None,
                "mae": sum(abs(error) for error in errors) / count if count else None,
                "rmse": math.sqrt(sum(error * error for error in errors) / count)
                if count
                else None,
                "bias": sum(errors) / count if count else None,
            }
        )
    levels: dict[tuple[str, str], list[float]] = defaultdict(list)
    for metric in metrics:
        if metric["mae"] is not None:
            levels[metric["level"], metric["target"]].append(metric["mae"])
    return {
        "method": "persistence_24h",
        "horizon_h": HORIZON_H,
        "scope": "descriptive synthetic reference; no training or model selection",
        "metrics": metrics,
        "macro_mae": [
            {
                "level": level,
                "target": target,
                "mae": sum(values) / len(values),
                "entities": len(values),
            }
            for (level, target), values in sorted(levels.items())
        ],
    }
