"""Reproducible first learning slice; only train and development-validation worlds."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import platform
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import torch

from hospitalos.synthetic.config import HospitalConfig
from hospitalos.synthetic.generate import generate
from hospitalos.synthetic.learning import _digest

from .adapter import LEGACY_CLOCK, MAPPING, export, load_observed
from .forecast import (
    FEATURES,
    LAGS,
    TARGETS,
    FloatArray,
    Inputs,
    baseline_predictions,
    build_inputs,
    climatology,
    fit,
    predict,
    score,
)


def write(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
    )


def configs(plan: dict[str, Any]) -> list[HospitalConfig]:
    """Frozen, disjoint topology cardinalities; seeds are repeats, never clinical validation."""
    rng = np.random.default_rng(plan["seed"])
    result = []
    for partition, key in (
        ("train", "train_unit_counts"),
        ("validation", "validation_unit_counts"),
        ("test", "reserved_test_unit_counts"),
    ):
        for index, count in enumerate(plan[key]):
            hospital = f"H15_{partition}_{index:02d}"
            pole_count = 2 if count < 6 else 3
            poles: list[dict[str, Any]] = [
                {"pole_id": f"{hospital}_P{j}", "units": []} for j in range(pole_count)
            ]
            for j in range(count):
                beds = int(rng.integers(20, 37))
                poles[j % pole_count]["units"].append(
                    {
                        "unit_id": f"{hospital}_U{j}",
                        "template": ("CSG", "MED_POLY", "CARDIO", "PNEUMO")[(j + index) % 4],
                        "beds": beds,
                        "isolation_beds": 4,
                        "oxygen_beds": min(beds, 18),
                        "arrival_scale": float(rng.uniform(0.85, 1.3)),
                    }
                )
            result.append(
                HospitalConfig.model_validate(
                    {
                        "hospital_id": hospital,
                        "seed": int(rng.integers(0, 2**31)),
                        "start": plan["start"],
                        "days": plan["days"],
                        "warmup_days": plan["warmup_days"],
                        "partition": partition,
                        "poles": poles,
                        "documentary": {
                            "staff_forecasts": "milestones_v1",
                            "downstream_confirmation": "request_delay_v1",
                        },
                        "dynamics": {
                            "arrivals": "v041" if index % 2 else "shared_bursts_v1",
                            "discharges": "daily_rounds_v1" if index % 2 else "rolling_v1",
                            "staffing": "persistent_absence_v1" if index % 2 else "shared_float_v1",
                        },
                        "observation": {"mode": "site_v1"},
                    }
                )
            )
    if "smr_comparison" in plan:
        from .smr_experiment import configure

        result = configure(result, plan["smr_comparison"])
    return result


def prepare(plan_path: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(output)
    plan = json.loads(plan_path.read_text())
    worlds = configs(plan)
    if set(plan["train_unit_counts"]) & set(plan["validation_unit_counts"]):
        raise ValueError("This experiment reserves validation cardinalities")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cohort15-", dir=output.parent) as temp:
        stage = Path(temp) / "cohort"
        stage.mkdir()
        write(stage / "plan.json", plan)
        write(stage / "registry.json", [c.model_dump(mode="json") for c in worlds])
        records = []
        for config in worlds:
            if config.partition == "test":
                continue  # No trajectories, observations or labels for the final reservation.
            root = stage / config.hospital_id
            generate(config, root / "truth")
            export(root / "truth", root / "observed")
            records.append(
                {
                    "hospital_id": config.hospital_id,
                    "partition": config.partition,
                    "config_sha256": config.fingerprint,
                    "truth_manifest_sha256": _digest(root / "truth/manifest.json"),
                    "observed_manifest_sha256": _digest(root / "observed/manifest.json"),
                }
            )
            print(
                json.dumps({"prepared": config.hospital_id, "units": len(config.units)}), flush=True
            )
        metadata = {
            "status": "complete",
            "data_role": "operational_experiment_cohort",
            "worlds": records,
            "test_opened": False,
            "reserved": [c.hospital_id for c in worlds if c.partition == "test"],
            "plan_sha256": _digest(stage / "plan.json"),
            "registry_sha256": _digest(stage / "registry.json"),
        }
        write(stage / "manifest.json", metadata)
        stage.rename(output)
    return metadata


def targets(source: Path, data: Inputs, expected_manifest: str) -> FloatArray:
    """Explicit label reader; called for validation only after forecasts are saved."""
    if _digest(source / "manifest.json") != expected_manifest:
        raise ValueError("Target source manifest changed")
    manifest = json.loads((source / "manifest.json").read_text())
    config = HospitalConfig.model_validate_json((source / "config.json").read_text())
    if config.partition == "test":
        raise ValueError("Reserved test targets cannot be read")
    path = source / "truth/units_hourly.csv"
    if _digest(path) != manifest["files_sha256"]["truth/units_hourly.csv"]:
        raise ValueError("Target file checksum mismatch")
    start = dt.datetime.combine(config.start, dt.time(), LEGACY_CLOCK).astimezone(dt.UTC)
    indices = {
        int((at - start).total_seconds() / 3600) + 24 - 1: i for i, at in enumerate(data.origins)
    }
    members = {n.entity_id: data.topology.descendants(n.entity_id) for n in data.nodes}
    result = np.zeros((len(data.origins), len(data.nodes), len(TARGETS)))
    seen: set[tuple[int, str]] = set()
    with path.open(newline="") as stream:
        for row in csv.DictReader(stream):
            h, unit = int(row["h"]), row["unit_id"]
            if h not in indices:
                continue
            if (
                (h, unit) in seen
                or unit not in config.unit_poles
                or row["hospital_id"] != config.hospital_id
            ):
                raise ValueError("Invalid target population")
            seen.add((h, unit))
            values = np.array([float(row[MAPPING[k]]) for k in TARGETS])
            if not np.isfinite(values).all() or (values < 0).any():
                raise ValueError("Invalid targets")
            for j, node in enumerate(data.nodes):
                if unit in members[node.entity_id]:
                    result[indices[h], j] += values
    if len(seen) != len(indices) * len(config.units):
        raise ValueError("Incomplete target grid")
    return result


def macro_scores(rows: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["n"]:
            key = tuple(row[k] for k in ("mode", "level", "target", "regime", "method"))
            grouped[key].append(row)
    result = []
    for key, group in sorted(grouped.items()):
        by_hospital: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in group:
            by_hospital[r["hospital_id"]].append(r)
        item: dict[str, Any] = dict(
            zip(("mode", "level", "target", "regime", "method"), key, strict=True)
        )
        item["hospitals"] = len(by_hospital)
        for metric in ("mae", "mse", "bias", "poisson_mean_deviance"):
            values = [
                np.mean([r[metric] for r in group if r[metric] is not None])
                for group in by_hospital.values()
                if any(r[metric] is not None for r in group)
            ]
            item[metric] = float(np.mean(values)) if values else None
        if key[-1] == "topology_mlp":
            baseline_group = grouped[(*key[:-1], "daily_same_hour")]
            baseline: dict[str, list[float]] = defaultdict(list)
            for r in baseline_group:
                baseline[r["hospital_id"]].append(r["mse"])
            differences = np.array(
                [
                    np.mean([r["mse"] for r in rs]) - np.mean(baseline[h])
                    for h, rs in sorted(by_hospital.items())
                ]
            )
            rng = np.random.default_rng(seed)
            boot = rng.choice(differences, (2000, len(differences)), replace=True).mean(axis=1)
            item["paired_mse_difference_vs_daily"] = float(differences.mean())
            item["exploratory_hospital_bootstrap_95pct"] = np.quantile(
                boot, [0.025, 0.975]
            ).tolist()
        result.append(item)
    return result


def run(cohort: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(output)
    metadata = json.loads((cohort / "manifest.json").read_text())
    if (
        metadata.get("status") != "complete"
        or metadata.get("data_role") != "operational_experiment_cohort"
        or metadata.get("test_opened") is not False
    ):
        raise ValueError("Incomplete or unauthorized experiment cohort")
    for name in ("plan", "registry"):
        if _digest(cohort / f"{name}.json") != metadata[f"{name}_sha256"]:
            raise ValueError("Experiment registry changed")
    plan = json.loads((cohort / "plan.json").read_text())
    if plan["horizon_h"] != 24 or plan["targets"] != list(TARGETS):
        raise ValueError("Unsupported first-experiment target")
    registry = [
        HospitalConfig.model_validate(c) for c in json.loads((cohort / "registry.json").read_text())
    ]
    expected = {c.hospital_id: c for c in registry if c.partition != "test"}
    records = metadata["worlds"]
    if len(records) != len(expected) or {r["hospital_id"] for r in records} != expected.keys():
        raise ValueError("Incomplete/duplicate experiment worlds")
    train_data, train_targets, validation = [], [], []
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".experiment15-", dir=output.parent) as temp:
        stage = Path(temp) / "result"
        (stage / "predictions").mkdir(parents=True)
        protocol = {
            **plan,
            "cohort_manifest_sha256": _digest(cohort / "manifest.json"),
            "code_sha256": {p.name: _digest(p) for p in Path(__file__).parent.glob("*.py")},
            "evaluation": "all scheduled origins; no exclusion for stale/missing inputs",
            "estimand": "conditional means; coherent sums only, no distribution/quantile claim",
        }
        write(stage / "protocol.json", protocol)  # Before reading any training/validation labels.
        for record in records:
            hospital = record["hospital_id"]
            root = cohort / hospital
            cfg = expected[hospital]
            if record["partition"] != cfg.partition or record["config_sha256"] != cfg.fingerprint:
                raise ValueError("World identity mismatch")
            if _digest(root / "observed/manifest.json") != record["observed_manifest_sha256"]:
                raise ValueError("Observed source changed")
            for mode in plan["modes"]:
                topology, observations, manifest = load_observed(root / "observed", mode)
                if (
                    manifest["partition"] != cfg.partition
                    or manifest["hospital_id"] != hospital
                    or manifest["source_manifest_sha256"] != record["truth_manifest_sha256"]
                ):
                    raise ValueError("Observation provenance mismatch")
                inputs = build_inputs(
                    topology,
                    observations,
                    manifest["modes"][mode]["frontier"],
                    dt.datetime.fromisoformat(manifest["start"]),
                    plan["days"] * 24,
                    timezone=LEGACY_CLOCK,
                    stride=plan["stride_h"],
                )
                if cfg.partition == "train":
                    train_data.append(inputs)
                    train_targets.append(
                        targets(root / "truth", inputs, record["truth_manifest_sha256"])
                    )
                else:
                    validation.append((record, mode, inputs))
            print(json.dumps({"inputs_ready": hospital}), flush=True)
        model, losses = fit(
            train_data,
            train_targets,
            epochs=plan["epochs"],
            seed=plan["seed"],
            learning_rate=plan["learning_rate"],
            batch_size=plan["batch_size"],
        )
        climate = climatology(train_data, train_targets)
        torch.save(model.state_dict(), stage / "model.pt")
        write(
            stage / "model_config.json",
            {
                "model_type": "TopologyForecaster_conditional_means_v1",
                "input_width": train_data[0].x.shape[-1],
                "features": FEATURES,
                "lags_h": LAGS,
                "targets": TARGETS,
                "weights_sha256": _digest(stage / "model.pt"),
                "scope": "synthetic_experiment_only_not_validated_for_real_hospitals",
            },
        )
        np.save(stage / "climatology.npy", climate)
        predictions: list[dict[str, FloatArray]] = []
        quality = []
        for record, mode, inputs in validation:
            pred = {**baseline_predictions(inputs, climate), "topology_mlp": predict(model, inputs)}
            predictions.append(pred)
            name = f"{record['hospital_id']}_{mode}.npz"
            np.savez_compressed(
                stage / "predictions" / name,
                topology_mlp=pred["topology_mlp"],
                persistence=pred["persistence"],
                daily_same_hour=pred["daily_same_hour"],
                train_climatology=pred["train_climatology"],
            )
            quality.append(
                {
                    "hospital_id": record["hospital_id"],
                    "mode": mode,
                    "origins": len(inputs.origins),
                    "nodes": len(inputs.nodes),
                    "missing_input_node_origins": int(np.isnan(inputs.ages).sum()),
                    "stale_input_node_origins": int((inputs.ages > 6).sum()),
                    "daily_fallback_values": int((~np.isfinite(inputs.daily)).sum()),
                    "coverage": 1.0,
                }
            )
        prediction_hashes = {p.name: _digest(p) for p in (stage / "predictions").glob("*.npz")}
        # Boundary: every validation forecast has been frozen before any target is opened.
        write(stage / "predictions_frozen.json", prediction_hashes)
        rows: list[dict[str, Any]] = []
        for (record, mode, inputs), pred in zip(validation, predictions, strict=True):
            y = targets(
                cohort / record["hospital_id"] / "truth", inputs, record["truth_manifest_sha256"]
            )
            rows.extend(
                {**r, "hospital_id": record["hospital_id"], "mode": mode}
                for r in score(inputs, y, pred)
            )
        report = {
            "status": "exploratory_validation_complete",
            "test_opened": False,
            "train_hospitals": sum(c.partition == "train" for c in registry),
            "validation_hospitals": sum(c.partition == "validation" for c in registry),
            "model_parameters": sum(p.numel() for p in model.parameters()),
            "training_loss": losses,
            "input_quality": quality,
            "macro": macro_scores(rows, plan["seed"]),
            "per_entity": rows,
            "limits": plan["limits"],
        }
        write(stage / "report.json", report)
        write(
            stage / "manifest.json",
            {
                "status": "complete",
                "synthetic_only": True,
                "protocol_sha256": _digest(stage / "protocol.json"),
                "test_opened": False,
                "runtime": {
                    "python": platform.python_version(),
                    "torch": torch.__version__,
                    "numpy": np.__version__,
                },
                "files_sha256": {
                    str(p.relative_to(stage)): _digest(p) for p in stage.rglob("*") if p.is_file()
                },
            },
        )
        stage.rename(output)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run"))
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--cohort", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare" and args.plan:
        prepare(args.plan, args.output)
    elif args.command == "run" and args.cohort:
        report = run(args.cohort, args.output)
        print(
            json.dumps(
                {
                    k: report[k]
                    for k in (
                        "status",
                        "train_hospitals",
                        "validation_hospitals",
                        "model_parameters",
                    )
                }
            )
        )
    else:
        parser.error("prepare requires --plan; run requires --cohort")


if __name__ == "__main__":
    main()
