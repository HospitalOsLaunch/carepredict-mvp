"""Build an observation/as-of dataset and a 24h reference from a verified truth run."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import platform
import tempfile
from collections.abc import Iterator
from importlib.metadata import version
from pathlib import Path
from typing import Any

from .asof import AsOfRow, replay
from .baseline24 import HORIZON_H, TARGET_UNITS, predict, score
from .config import HospitalConfig, load_config
from .generate import _csv, _jsonl, source_hashes
from .observations import observe_snapshots


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_source(source: Path) -> tuple[HospitalConfig, str]:
    manifest = json.loads((source / "manifest.json").read_text())
    if (
        manifest.get("status") != "complete"
        or manifest.get("synthetic_only") is not True
        or manifest.get("data_role") != "simulation_truth_not_training_inputs"
    ):
        raise ValueError("Source is not a completed synthetic truth run")
    for name in ("config.json", "truth/events.jsonl.gz", "truth/units_hourly.csv"):
        if _digest(source / name) != manifest["files_sha256"].get(name):
            raise ValueError(f"Source checksum mismatch: {name}")
    config = load_config(source / "config.json")
    if (
        config.fingerprint != manifest["config_sha256"]
        or config.hospital_id != manifest["hospital_id"]
    ):
        raise ValueError("Source config does not match manifest")
    return config, _digest(source / "manifest.json")


def _events(source: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(source / "truth/events.jsonl.gz", "rt", encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def build_labels(source: Path, config: HospitalConfig, rows: list[AsOfRow]) -> list[dict[str, Any]]:
    """Only this side of the pipeline reads future truth; no features are returned."""
    truth: dict[tuple[int, str], dict[str, float]] = {}
    units = config.unit_poles
    with (source / "truth/units_hourly.csv").open(newline="", encoding="utf-8") as stream:
        for raw in csv.DictReader(stream):
            hour, unit = int(raw["h"]), raw["unit_id"]
            if (
                raw["hospital_id"] != config.hospital_id
                or units.get(unit) != raw["pole_id"]
                or not 0 <= hour < config.days * 24
                or (hour, unit) in truth
            ):
                raise ValueError("Invalid or duplicate truth state")
            values = {name: float(raw[name]) for name in TARGET_UNITS}
            if any(not math.isfinite(value) or value < 0 for value in values.values()):
                raise ValueError("Invalid truth target")
            truth[hour, unit] = values
    if len(truth) != config.days * 24 * len(config.units):
        raise ValueError("Incomplete hourly truth grid")
    members = {unit.unit_id: [unit.unit_id] for unit in config.units}
    members.update({pole.pole_id: [unit.unit_id for unit in pole.units] for pole in config.poles})
    members[config.hospital_id] = list(units)
    labels = []
    for row in rows:
        target_h = row.decision_h + HORIZON_H
        censored = target_h > config.days * 24
        # Truth h is the end of [h,h+1). Target boundary T therefore uses row T-1.
        labels.append(
            {
                "sample_id": row.sample_id,
                "hospital_id": row.hospital_id,
                "entity_id": row.entity_id,
                "level": row.level,
                "partition": row.partition,
                "decision_h": row.decision_h,
                "target_h": target_h,
                "horizon_h": HORIZON_H,
                "censored": censored,
                **{
                    f"target_{name}": None
                    if censored
                    else sum(truth[target_h - 1, unit][name] for unit in members[row.entity_id])
                    for name in TARGET_UNITS
                },
            }
        )
    return labels


def prepare_learning_run(
    source: Path, output: Path, *, stale_after_h: float = 6.0
) -> dict[str, Any]:
    """Read-only input; complete output published atomically to a new directory."""
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    if source.resolve() in output.resolve().parents:
        raise ValueError("Output must be outside the immutable truth run")
    config, input_hash = verify_source(source)
    settings = {
        "profile": "v041_unit_snapshot_end_of_hour_v1",
        "seed": config.seed,
        "stale_after_h": stale_after_h,
        "horizon_h": HORIZON_H,
    }
    hashes = source_hashes()
    run_id = hashlib.sha256(
        json.dumps(
            {"input": input_hash, "settings": settings, "code": hashes}, sort_keys=True
        ).encode()
    ).hexdigest()[:24]
    deliveries = observe_snapshots(_events(source), config)
    features = list(replay(deliveries, config, run_id=run_id, stale_after_h=stale_after_h))
    # Predictions are computed before any future label is read.
    predictions = predict(features)
    labels = build_labels(source, config, features)
    report = score(predictions, labels)
    report.update(hospital_id=config.hospital_id, partition=config.partition, run_id=run_id)
    report["observation_quality"] = {
        "deliveries": len(deliveries),
        "snapshot_events_available": len({row.event_id for row in deliveries}),
        "snapshots_not_delivered_by_cutoff": (
            (config.days + config.warmup_days) * 24 * len(config.units)
            - len({row.event_id for row in deliveries})
        ),
        "revisions": sum(row.event_version > 1 for row in deliveries),
        "transport_duplicates": len(deliveries)
        - len({(row.event_id, row.event_version) for row in deliveries}),
        "unit_rows_missing": sum(row.missing for row in features if row.level == "unit"),
        "unit_rows_stale": sum(row.stale for row in features if row.level == "unit"),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".asof-", dir=output.parent) as temp:
        staging = Path(temp) / "run"
        for directory in ("observed", "features", "targets", "evaluation"):
            (staging / directory).mkdir(parents=True, exist_ok=True)
        _jsonl(
            staging / "observed/unit_states.jsonl.gz",
            (row.model_dump(mode="json") for row in deliveries),
        )
        _jsonl(
            staging / "features/asof.jsonl.gz", (row.model_dump(mode="json") for row in features)
        )
        _csv(staging / "targets/occupancy_load_queue_24h.csv", labels)
        _csv(staging / "evaluation/persistence_24h.csv", predictions)
        (staging / "evaluation/metrics.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        (staging / "config.json").write_text(
            config.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        manifest = {
            "schema_version": "0.2",
            "status": "complete",
            "synthetic_only": True,
            "data_role": "observations_features_targets_separated",
            "run_id": run_id,
            "input_manifest_sha256": input_hash,
            "source_sha256": hashes,
            "runtime": {
                "python": platform.python_version(),
                **{name: version(name) for name in ("numpy", "pandas", "pydantic")},
            },
            "settings": settings,
            "hospital_id": config.hospital_id,
            "partition": config.partition,
            "counts": {
                "features": len(features),
                "labels": len(labels),
                "deliveries": len(deliveries),
            },
            "clock": "fixed UTC+01:00; decision at boundary h; snapshot h-1 ends at h",
            "scope": "unit snapshots only; no patient trajectory/notes or learned model",
            "files_sha256": {
                str(path.relative_to(staging)): _digest(path)
                for path in sorted(staging.rglob("*"))
                if path.is_file()
            },
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
            + "\n",
            encoding="utf-8",
        )
        staging.rename(output)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="As-of unit states and 24h persistence reference")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stale-after-hours", type=float, default=6.0)
    args = parser.parse_args()
    try:
        report = prepare_learning_run(
            args.source, args.output, stale_after_h=args.stale_after_hours
        )
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"As-of preparation failed: {exc}\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "macro_mae": report["macro_mae"],
                "observation_quality": report["observation_quality"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
