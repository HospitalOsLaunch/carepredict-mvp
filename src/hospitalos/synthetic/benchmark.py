"""Frozen, train-only 24h references; final-test worlds are never accepted here."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import json
import math
import pickle
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from sklearn.ensemble import HistGradientBoostingRegressor  # type: ignore[import-untyped]
from threadpoolctl import threadpool_limits  # type: ignore[import-untyped]

from .asof import AsOfRow
from .baseline24 import HORIZON_H, TARGET_UNITS
from .cohort import _runtime, _sha, _write, load_registry
from .config import HospitalConfig
from .generate import _csv, source_hashes
from .observations import ObservedState
from .registry import Registry, World

TARGETS = tuple(TARGET_UNITS)
METHODS = ("persistence_24h", "seasonal_week_24h", "gradient_boosting_24h")
CONTEXT_H = 168
SEASONAL_LAG = 168 - HORIZON_H
TEMPLATES = ("MED_POLY", "CSG", "PNEUMO", "CARDIO")
FIELDS = tuple(ObservedState.model_fields)
FloatArray = NDArray[np.float64]


def model_parameters() -> dict[str, Any]:
    return {
        "loss": "absolute_error",
        "learning_rate": 0.05,
        "max_iter": 100,
        "max_leaf_nodes": 15,
        "min_samples_leaf": 100,
        "l2_regularization": 1.0,
        "early_stopping": False,
        "random_state": 1701,
    }


def feature_names() -> list[str]:
    return [f"lag{lag}_{field}_per_open_bed" for lag in (0, 24, 168) for field in FIELDS] + [
        "open_beds",
        "age_hours",
        "hour_sin",
        "hour_cos",
        "weekday_sin",
        "weekday_cos",
        "year_sin",
        "year_cos",
        *[f"specialty_{name}" for name in TEMPLATES],
    ]


def contract() -> dict[str, Any]:
    return {
        "protocol_id": "BASELINES_24H_V1",
        "synthetic_only": True,
        "status": "engineering_validation_not_signed_final_protocol",
        "horizon_h": HORIZON_H,
        "context_h": CONTEXT_H,
        "targets": TARGET_UNITS,
        "methods": METHODS,
        "seasonal_lag_h": SEASONAL_LAG,
        "features": feature_names(),
        "model_parameters": model_parameters(),
        "fit": "train only; shared unit regressor per target; no tuning or early stop",
        "sample_weights": "equal hospitals, replicates within hospital, rows within run",
        "prediction": "nonnegative unit forecasts, summed to poles and hospital; no occupancy cap",
        "common_support": "current and t-144 observations fresh; all aggregate members",
        "lags": "observations as known at t, t-24, t-168; stale/missing lag values become NaN",
        "scaling": "state inputs and training targets divided by max(1, current open beds)",
        "scoring": "MAE, RMSE, bias per entity/run; mean entities then replicates then hospitals",
        "exclusions": "first 168h, censored targets, test, patients, notes, actions",
        "gate": "descriptive only; no confidence interval, significance or G1-G4/SYN pass",
        "source_sha256": source_hashes(),
        "runtime": {**_runtime(), "scikit-learn": version("scikit-learn")},
    }


def _safe_child(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise ValueError("Cohort path escapes root")
    return path


def verify_inputs(registry_path: Path, cohort_path: Path) -> tuple[Registry, list[dict[str, Any]]]:
    registry = load_registry(registry_path)
    manifest = json.loads((cohort_path / "manifest.json").read_text())
    if (
        manifest.get("status") != "complete"
        or manifest.get("synthetic_only") is not True
        or manifest.get("data_role") != "partitioned_cohort_runs"
        or manifest.get("with_learning") is not True
        or manifest.get("selected_partitions") != ["train", "validation"]
        or manifest.get("test_access") != {"opened": False, "protocol": None}
    ):
        raise ValueError("Benchmark accepts only a complete train/validation synthetic cohort")
    if (
        manifest["registry_sha256"] != registry.fingerprint
        or manifest["registry_manifest_sha256"] != _sha(registry_path / "manifest.json")
        or manifest["source_sha256"] != source_hashes()
    ):
        raise ValueError("Cohort provenance mismatch")
    expected = {w.world_id: w for w in registry.worlds if w.config.partition != "test"}
    records: list[dict[str, Any]] = manifest["worlds"]
    if len(records) != len(expected) or {r["world_id"] for r in records} != set(expected):
        raise ValueError("Incomplete or duplicate cohort worlds")
    if sorted(manifest["reserved_world_ids"]) != sorted(
        w.world_id for w in registry.worlds if w.config.partition == "test"
    ):
        raise ValueError("Test reservation mismatch")
    for record in records:
        world = expected[record["world_id"]]
        cfg = world.config
        for field, value in {
            "hospital_id": cfg.hospital_id,
            "partition": cfg.partition,
            "replicate": world.replicate,
            "structure_sha256": world.structure_sha256,
            "config_sha256": cfg.fingerprint,
        }.items():
            if record.get(field) != value:
                raise ValueError(f"World metadata mismatch: {field}")
        learning = _safe_child(cohort_path, record["learning_path"])
        if _sha(learning / "manifest.json") != record["learning_manifest_sha256"]:
            raise ValueError("Learning manifest checksum mismatch")
        metadata = json.loads((learning / "manifest.json").read_text())
        if (
            metadata.get("status") != "complete"
            or metadata.get("synthetic_only") is not True
            or metadata.get("data_role") != "observations_features_targets_separated"
            or metadata["run_id"] != record["learning_run_id"]
            or metadata["hospital_id"] != cfg.hospital_id
            or metadata["partition"] != cfg.partition
            or metadata["settings"]["horizon_h"] != HORIZON_H
            or metadata["input_manifest_sha256"] != record["truth_manifest_sha256"]
            or metadata["source_sha256"] != manifest["source_sha256"]
        ):
            raise ValueError("Learning provenance mismatch")
        for name in (
            "config.json",
            "features/asof.jsonl.gz",
            "targets/occupancy_load_queue_24h.csv",
        ):
            if _sha(learning / name) != metadata["files_sha256"].get(name):
                raise ValueError(f"Learning checksum mismatch: {name}")
        if HospitalConfig.model_validate_json((learning / "config.json").read_text()) != cfg:
            raise ValueError("Learning configuration mismatch")
    return registry, records


def freeze_protocol(registry_path: Path, cohort_path: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(output)
    registry, _ = verify_inputs(registry_path, cohort_path)
    protocol = {
        **contract(),
        "registry_sha256": registry.fingerprint,
        "registry_manifest_sha256": _sha(registry_path / "manifest.json"),
        "cohort_manifest_sha256": _sha(cohort_path / "manifest.json"),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation makes the protocol immutable through this command.
    with output.open("x", encoding="utf-8") as stream:
        json.dump(protocol, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return protocol


@dataclass(frozen=True)
class Samples:
    rows: tuple[AsOfRow, ...]
    x: FloatArray
    scales: FloatArray
    persistence: FloatArray
    seasonal: FloatArray
    eligible: NDArray[np.bool_]


def prepare_samples(rows: Iterable[AsOfRow], config: HospitalConfig, run_id: str) -> Samples:
    """Feature construction has no labels/truth argument and never uses future rows."""
    history: dict[tuple[str, int], AsOfRow] = {}
    members = {u.unit_id for u in config.units}
    for row in rows:
        if (
            row.hospital_id != config.hospital_id
            or row.partition != config.partition
            or row.run_id != run_id
            or not 0 <= row.decision_h < config.days * 24
            or row.sample_id != f"{run_id}:{row.entity_id}@{row.decision_h}"
        ):
            raise ValueError("Feature identity mismatch")
        if row.level != "unit":
            continue
        key = (row.entity_id, row.decision_h)
        if row.entity_id not in members or key in history or row.total_units != 1:
            raise ValueError("Invalid or duplicate unit feature")
        if any(s.unit_id != row.entity_id for s in row.sources):
            raise ValueError("Feature source unit mismatch")
        history[key] = row
    if len(history) != len(members) * config.days * 24:
        raise ValueError("Incomplete unit feature grid")
    selected = tuple(
        history[u.unit_id, h] for h in range(CONTEXT_H, config.days * 24) for u in config.units
    )
    if not selected:
        raise ValueError("Cohort shorter than context window")
    x = np.full((len(selected), len(feature_names())), np.nan, dtype=np.float64)
    scales = np.ones(len(selected), dtype=np.float64)
    persistence = np.full((len(selected), len(TARGETS)), np.nan, dtype=np.float64)
    seasonal = persistence.copy()
    eligible = np.zeros(len(selected), dtype=np.bool_)
    templates = {u.unit_id: u.template for u in config.units}
    for i, row in enumerate(selected):
        fresh = row.values is not None and not row.stale
        old = history[row.entity_id, row.decision_h - SEASONAL_LAG]
        eligible[i] = fresh and old.values is not None and not old.stale
        if row.values is not None:
            scales[i] = max(1.0, row.values.lits_ouverts)
            persistence[i] = [getattr(row.values, target) for target in TARGETS]
        if old.values is not None:
            seasonal[i] = [getattr(old.values, target) for target in TARGETS]
        for j, lag in enumerate((0, 24, 168)):
            prior = history[row.entity_id, row.decision_h - lag]
            if prior.values is not None and not prior.stale:
                x[i, j * len(FIELDS) : (j + 1) * len(FIELDS)] = [
                    getattr(prior.values, field) / scales[i] for field in FIELDS
                ]
        clock = dt.datetime.combine(config.start, dt.time()) + dt.timedelta(hours=row.decision_h)
        phases = (
            clock.hour / 24,
            clock.weekday() / 7,
            (clock.timetuple().tm_yday - 1) / (366 if _leap(clock.year) else 365),
        )
        x[i, 3 * len(FIELDS) :] = [
            scales[i],
            row.max_age_h if row.max_age_h is not None else math.nan,
            *[f(2 * math.pi * phase) for phase in phases for f in (math.sin, math.cos)],
            *[float(templates[row.entity_id] == name) for name in TEMPLATES],
        ]
    return Samples(selected, x, scales, persistence, seasonal, eligible)


def _leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def read_samples(root: Path, world: World, record: dict[str, Any]) -> Samples:
    with gzip.open(root / "features/asof.jsonl.gz", "rt", encoding="utf-8") as stream:
        return prepare_samples(
            (AsOfRow.model_validate_json(line) for line in stream),
            world.config,
            record["learning_run_id"],
        )


def read_targets(root: Path, samples: Samples, config: HospitalConfig) -> FloatArray:
    """Future labels are isolated here; reject duplicates, invalid horizon and censor leakage."""
    lookup = {row.sample_id: i for i, row in enumerate(samples.rows)}
    y = np.full((len(samples.rows), len(TARGETS)), np.nan, dtype=np.float64)
    seen: set[str] = set()
    all_seen: set[str] = set()
    with (root / "targets/occupancy_load_queue_24h.csv").open(newline="") as stream:
        for raw in csv.DictReader(stream):
            sid = raw["sample_id"]
            if sid in all_seen:
                raise ValueError("Duplicate target sample")
            all_seen.add(sid)
            if sid not in lookup:
                continue
            i = lookup[sid]
            row = samples.rows[i]
            target_h = row.decision_h + HORIZON_H
            if any(
                raw[field] != str(value)
                for field, value in {
                    "hospital_id": row.hospital_id,
                    "entity_id": row.entity_id,
                    "level": "unit",
                    "partition": row.partition,
                    "decision_h": row.decision_h,
                    "target_h": target_h,
                    "horizon_h": HORIZON_H,
                    "censored": target_h > config.days * 24,
                }.items()
            ):
                raise ValueError("Target metadata or censoring mismatch")
            seen.add(sid)
            for j, target in enumerate(TARGETS):
                value = raw[f"target_{target}"]
                if target_h > config.days * 24:
                    if value != "":
                        raise ValueError("Censored target leaked")
                else:
                    y[i, j] = float(value)
                    if not np.isfinite(y[i, j]) or y[i, j] < 0:
                        raise ValueError("Invalid target")
    if seen != set(lookup):
        raise ValueError("Missing target sample")
    return y


def aggregate_predictions(
    samples: Samples,
    predictions: dict[str, FloatArray],
    config: HospitalConfig,
) -> tuple[list[dict[str, Any]], dict[tuple[str, int], list[int]]]:
    """Produce coherent forecasts before validation labels are opened."""
    groups: dict[tuple[str, int], list[int]] = defaultdict(list)
    levels = {u.unit_id: "unit" for u in config.units}
    levels.update({p.pole_id: "pole" for p in config.poles})
    levels[config.hospital_id] = "hospital"
    for i, row in enumerate(samples.rows):
        for entity in (row.entity_id, config.unit_poles[row.entity_id], config.hospital_id):
            groups[entity, row.decision_h].append(i)
    outputs = []
    for (entity, hour), indexes in groups.items():
        valid = bool(samples.eligible[indexes].all())
        for method in METHODS:
            forecast = predictions[method][indexes].sum(axis=0)
            if valid and (not np.isfinite(forecast).all() or (forecast < 0).any()):
                raise ValueError("Invalid prediction")
            outputs.append(
                {
                    "hospital_id": config.hospital_id,
                    "partition": config.partition,
                    "entity_id": entity,
                    "level": levels[entity],
                    "decision_h": hour,
                    "target_h": hour + HORIZON_H,
                    "horizon_h": HORIZON_H,
                    "method": method,
                    "status": "available" if valid else "common_support_abstention",
                    **{
                        f"prediction_{t}": float(forecast[j]) if valid else None
                        for j, t in enumerate(TARGETS)
                    },
                }
            )
    return outputs, groups


def score_world(
    forecasts: list[dict[str, Any]],
    groups: dict[tuple[str, int], list[int]],
    y: FloatArray,
    world: World,
) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for forecast in forecasts:
        indexes = groups[forecast["entity_id"], forecast["decision_h"]]
        target = y[indexes].sum(axis=0)
        censored = forecast["target_h"] > world.config.days * 24
        if censored != bool(np.isnan(target).all()) or (
            not censored and not np.isfinite(target).all()
        ):
            raise ValueError("Incomplete aggregate target")
        for j, name in enumerate(TARGETS):
            key = (forecast["method"], forecast["level"], forecast["entity_id"], name)
            bucket = buckets.setdefault(
                key, {"n_censored": 0, "n_eligible": 0, "n_abstained": 0, "errors": []}
            )
            if censored:
                bucket["n_censored"] += 1
            else:
                bucket["n_eligible"] += 1
                if forecast["status"] != "available":
                    bucket["n_abstained"] += 1
                else:
                    bucket["errors"].append(forecast[f"prediction_{name}"] - target[j])
    metrics = []
    for (method, level, entity, target_name), bucket in sorted(buckets.items()):
        errors = np.asarray(bucket.pop("errors"), dtype=np.float64)
        metrics.append(
            {
                "world_id": world.world_id,
                "hospital_id": world.config.hospital_id,
                "replicate": world.replicate,
                "partition": world.config.partition,
                "method": method,
                "level": level,
                "entity_id": entity,
                "target": target_name,
                "unit": TARGET_UNITS[target_name],
                **bucket,
                "n_scored": len(errors),
                "coverage": len(errors) / bucket["n_eligible"] if bucket["n_eligible"] else 0.0,
                "mae": float(np.abs(errors).mean()) if len(errors) else None,
                "rmse": float(np.sqrt((errors**2).mean())) if len(errors) else None,
                "bias": float(errors.mean()) if len(errors) else None,
            }
        )
    return metrics


def summarize(metrics: list[dict[str, Any]]) -> dict[str, Any]:
    """Equal entities within run, runs within hospital, hospitals; never pool hourly rows."""
    by_run: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in metrics:
        by_run[
            row["hospital_id"], row["world_id"], row["method"], row["level"], row["target"]
        ].append(row)
    by_hospital: dict[tuple[str, str, str, str], list[dict[str, float]]] = defaultdict(list)
    for (hospital, _, method, level, target), entries in by_run.items():
        if any(r["n_scored"] == 0 for r in entries):
            raise ValueError("An entity has no scored samples; cannot silently omit it")
        by_hospital[hospital, method, level, target].append(
            {
                metric: float(np.mean([r[metric] for r in entries]))
                for metric in ("mae", "rmse", "bias", "coverage")
            }
        )
    hospital_rows = []
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for (hospital, method, level, target), entries in sorted(by_hospital.items()):
        row = {
            "hospital_id": hospital,
            "method": method,
            "level": level,
            "target": target,
            "n_replicates": len(entries),
            **{
                m: float(np.mean([r[m] for r in entries]))
                for m in ("mae", "rmse", "bias", "coverage")
            },
        }
        hospital_rows.append(row)
        grouped[method, level, target].append(row)
    macro = [
        {
            "method": method,
            "level": level,
            "target": target,
            "unit": TARGET_UNITS[target],
            "n_hospitals": len(entries),
            **{
                m: float(np.mean([r[m] for r in entries]))
                for m in ("mae", "rmse", "bias", "coverage")
            },
        }
        for (method, level, target), entries in sorted(grouped.items())
    ]
    return {"hospital_metrics": hospital_rows, "macro": macro}


def run_benchmark(
    registry_path: Path, cohort_path: Path, protocol_path: Path, output: Path
) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(output)
    if any(output.resolve().is_relative_to(p.resolve()) for p in (registry_path, cohort_path)):
        raise ValueError("Output must be outside immutable input directories")
    protocol = json.loads(protocol_path.read_text())
    expected = json.loads(
        json.dumps(
            {
                **contract(),
                "registry_sha256": load_registry(registry_path).fingerprint,
                "registry_manifest_sha256": _sha(registry_path / "manifest.json"),
                "cohort_manifest_sha256": _sha(cohort_path / "manifest.json"),
            }
        )
    )
    if protocol != expected:
        raise ValueError("Frozen protocol, source, runtime or input changed")
    registry, records = verify_inputs(registry_path, cohort_path)
    worlds = {w.world_id: w for w in registry.worlds}
    train = [r for r in records if r["partition"] == "train"]
    validation = [r for r in records if r["partition"] == "validation"]
    xs, ys, weights = [], [], []
    training_rows = []
    repeats = Counter(r["hospital_id"] for r in train)
    for record in train:
        world = worlds[record["world_id"]]
        root = _safe_child(cohort_path, record["learning_path"])
        samples = read_samples(root, world, record)
        y = read_targets(root, samples, world.config)
        mask = samples.eligible & np.isfinite(y).all(axis=1)
        if not mask.any():
            raise ValueError("No training samples for a world")
        xs.append(samples.x[mask])
        ys.append(y[mask] / samples.scales[mask, None])
        weights.append(
            np.full(int(mask.sum()), 1.0 / (mask.sum() * repeats[record["hospital_id"]]))
        )
        training_rows.append(
            {
                "world_id": world.world_id,
                "hospital_id": world.config.hospital_id,
                "replicate": world.replicate,
                "n_fit": int(mask.sum()),
            }
        )
    x_train, y_train, sample_weights = (
        np.concatenate(xs),
        np.concatenate(ys),
        np.concatenate(weights),
    )
    sample_weights /= sample_weights.mean()
    models: list[Any] = []
    # Fixed hyperparameters, no random validation split and no validation-label access during fit.
    with threadpool_limits(limits=1):
        for j in range(len(TARGETS)):
            model = HistGradientBoostingRegressor(**model_parameters())
            model.fit(x_train, y_train[:, j], sample_weight=sample_weights)
            models.append(model)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".benchmark-", dir=output.parent) as temporary:
        staging = Path(temporary) / "benchmark"
        staging.mkdir()
        _write(staging / "protocol.json", protocol)
        # Locally generated models; this pipeline never unpickles input files.
        (staging / "models.pkl").write_bytes(
            pickle.dumps(dict(zip(TARGETS, models, strict=True)), protocol=5)
        )
        metrics = []
        for record in validation:
            world = worlds[record["world_id"]]
            root = _safe_child(cohort_path, record["learning_path"])
            samples = read_samples(root, world, record)
            gb = np.full_like(samples.persistence, np.nan)
            with threadpool_limits(limits=1):
                for j, model in enumerate(models):
                    gb[samples.eligible, j] = np.maximum(
                        0,
                        model.predict(samples.x[samples.eligible])
                        * samples.scales[samples.eligible],
                    )
            forecasts, groups = aggregate_predictions(
                samples,
                dict(zip(METHODS, (samples.persistence, samples.seasonal, gb), strict=True)),
                world.config,
            )
            for row in forecasts:
                row["world_id"] = world.world_id
            _csv(staging / f"{world.world_id}_predictions.csv", forecasts)
            # Validation predictions are fixed and written before opening validation labels.
            y = read_targets(root, samples, world.config)
            metrics.extend(score_world(forecasts, groups, y, world))
        report = {
            "partition": "validation",
            "horizon_h": HORIZON_H,
            "training_rows": training_rows,
            "entity_metrics": metrics,
            **summarize(metrics),
            "interpretation": "Small synthetic structural validation; no gate or real-world claim",
            "test_opened": False,
        }
        _write(staging / "metrics.json", report)
        manifest = {
            "status": "complete",
            "synthetic_only": True,
            "data_role": "reference_benchmark",
            "protocol_sha256": _sha(protocol_path),
            "cohort_manifest_sha256": _sha(cohort_path / "manifest.json"),
            "source_sha256": source_hashes(),
            "runtime": protocol["runtime"],
            "test_opened": False,
            "train_worlds": [r["world_id"] for r in train],
            "validation_worlds": [r["world_id"] for r in validation],
            "reserved_test_worlds": [
                w.world_id for w in registry.worlds if w.config.partition == "test"
            ],
            "files_sha256": {p.name: _sha(p) for p in sorted(staging.iterdir())},
        }
        _write(staging / "manifest.json", manifest)
        staging.rename(output)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "run"))
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--cohort", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "freeze":
            result = freeze_protocol(args.registry, args.cohort, args.protocol)
            print(json.dumps({"protocol_id": result["protocol_id"], "test_opened": False}))
        else:
            if args.output is None:
                parser.error("run requires --output")
            result = run_benchmark(args.registry, args.cohort, args.protocol, args.output)
            print(json.dumps({"macro": result["macro"], "test_opened": result["test_opened"]}))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"Benchmark failed: {exc}\n")


if __name__ == "__main__":
    main()
