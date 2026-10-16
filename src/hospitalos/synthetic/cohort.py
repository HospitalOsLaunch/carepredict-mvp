"""Freeze a registry, then materialize selected partitions without opening test by default."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import tempfile
from importlib.metadata import version
from pathlib import Path
from typing import Any

from .generate import generate, source_hashes
from .learning import prepare_learning_run
from .patient_census import CensusProfile
from .patient_learning import prepare_patient_run
from .registry import CohortPlan, Partition, Registry, compile_registry


def _runtime() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        **{name: version(name) for name in ("numpy", "pandas", "pydantic")},
    }


def _sha(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _write(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def freeze(plan: CohortPlan, output: Path) -> Registry:
    if output.exists():
        raise FileExistsError(output)
    registry = compile_registry(plan)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cohort-", dir=output.parent) as temporary:
        staging = Path(temporary) / "registry"
        staging.mkdir()
        _write(staging / "registry.json", registry.model_dump(mode="json"))
        _write(
            staging / "manifest.json",
            {
                "schema_version": "0.1",
                "status": "frozen",
                "synthetic_only": True,
                "data_role": "cohort_registry_no_trajectories",
                "registry_sha256": registry.fingerprint,
                "files_sha256": {"registry.json": _sha(staging / "registry.json")},
                "source_sha256": source_hashes(),
                "runtime": _runtime(),
                **registry.summary(),
            },
        )
        staging.rename(output)
    return registry


def load_registry(source: Path) -> Registry:
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if (
        manifest.get("status") != "frozen"
        or manifest.get("synthetic_only") is not True
        or manifest.get("data_role") != "cohort_registry_no_trajectories"
    ):
        raise ValueError("Source is not a frozen synthetic registry")
    if manifest["files_sha256"] != {"registry.json": _sha(source / "registry.json")}:
        raise ValueError("Registry file checksum mismatch")
    registry = Registry.model_validate_json((source / "registry.json").read_text(encoding="utf-8"))
    if manifest["registry_sha256"] != registry.fingerprint:
        raise ValueError("Registry content fingerprint mismatch")
    if manifest["source_sha256"] != source_hashes():
        raise ValueError("Source code changed since freeze; create a new registry version")
    if manifest["runtime"] != _runtime():
        raise ValueError("Runtime changed since freeze; restore versions or freeze a new registry")
    return registry


def materialize(
    source: Path,
    output: Path,
    *,
    partitions: tuple[Partition, ...] = ("train", "validation"),
    with_learning: bool = False,
    with_patients: bool = False,
    with_census: bool = False,
    with_care: bool = False,
    test_protocol: str | None = None,
) -> dict[str, Any]:
    """Atomic batch; source registry remains unchanged. No model fitting or pooling."""
    if output.exists():
        raise FileExistsError(output)
    if with_census and not with_patients:
        raise ValueError("Census reconciliation requires with_patients")
    if with_care and not with_patients:
        raise ValueError("Care enrichment requires with_patients")
    if not partitions or len(set(partitions)) != len(partitions):
        raise ValueError("Choose nonempty, unique partitions")
    if not set(partitions) <= {"train", "validation", "test"}:
        raise ValueError("Unknown partition")
    if "test" in partitions and not (test_protocol and test_protocol.strip()):
        raise ValueError("Opening test requires an explicit test_protocol identifier")
    if "test" not in partitions and test_protocol is not None:
        raise ValueError("test_protocol is only valid when opening test")
    registry = load_registry(source)
    source = source.resolve()
    output = output.resolve()
    if output.is_relative_to(source):
        raise ValueError("Output must be outside the frozen registry")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cohort-runs-", dir=output.parent) as temporary:
        staging = Path(temporary) / "batch"
        staging.mkdir()
        records = []
        for world in registry.worlds:
            config = world.config
            if config.partition not in partitions:
                continue
            relative = Path(config.partition) / world.world_id
            root = staging / relative
            truth = generate(config, root / "truth")
            record: dict[str, Any] = {
                "world_id": world.world_id,
                "hospital_id": config.hospital_id,
                "partition": config.partition,
                "replicate": world.replicate,
                "structure_sha256": world.structure_sha256,
                "config_sha256": config.fingerprint,
                "dynamics": config.dynamics.model_dump(mode="json"),
                "documentary": config.documentary.model_dump(mode="json"),
                "truth_path": (relative / "truth").as_posix(),
                "truth_manifest_sha256": _sha(root / "truth/manifest.json"),
                "counts": truth["counts"],
                "checks": truth["checks"],
            }
            if with_learning:
                prepare_learning_run(root / "truth", root / "learning")
                learning = json.loads((root / "learning/manifest.json").read_text())
                record.update(
                    learning_path=(relative / "learning").as_posix(),
                    learning_run_id=learning["run_id"],
                    learning_manifest_sha256=_sha(root / "learning/manifest.json"),
                    learning_counts=learning["counts"],
                )
            if with_patients:
                patient = prepare_patient_run(
                    root / "truth",
                    root / "patients",
                    census_profile=CensusProfile() if with_census else None,
                    with_care=with_care,
                )
                record.update(
                    patient_path=(relative / "patients").as_posix(),
                    patient_run_id=patient["run_id"],
                    patient_manifest_sha256=_sha(root / "patients/manifest.json"),
                    patient_counts=patient["counts"],
                )
            records.append(record)
        manifest = {
            "schema_version": "0.1",
            "status": "complete",
            "synthetic_only": True,
            "data_role": "partitioned_cohort_runs",
            "registry_sha256": registry.fingerprint,
            "registry_manifest_sha256": _sha(source / "manifest.json"),
            "source_sha256": source_hashes(),
            "selected_partitions": sorted(partitions),
            "test_access": {"opened": "test" in partitions, "protocol": test_protocol},
            "with_learning": with_learning,
            "with_patients": with_patients,
            "with_census": with_census,
            "with_care": with_care,
            "worlds": records,
            "reserved_world_ids": [
                w.world_id for w in registry.worlds if w.config.partition not in partitions
            ],
            "join_key": "(world_id, entity_id, decision_h); patient/event IDs also need world_id",
            "summary": registry.summary(),
        }
        _write(staging / "manifest.json", manifest)
        staging.rename(output)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthetic cohort registry and partitioned runs")
    commands = parser.add_subparsers(dest="command", required=True)
    plan_parser = commands.add_parser("freeze")
    plan_parser.add_argument("--plan", type=Path, required=True)
    plan_parser.add_argument("--output", type=Path, required=True)
    run_parser = commands.add_parser("generate")
    run_parser.add_argument("--registry", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument(
        "--partitions",
        nargs="+",
        choices=["train", "validation", "test"],
        default=["train", "validation"],
    )
    run_parser.add_argument("--with-learning", action="store_true")
    run_parser.add_argument("--with-patients", action="store_true")
    run_parser.add_argument("--with-census", action="store_true")
    run_parser.add_argument("--with-care", action="store_true")
    run_parser.add_argument("--test-protocol")
    args = parser.parse_args()
    try:
        if args.command == "freeze":
            plan = CohortPlan.model_validate_json(args.plan.read_text(encoding="utf-8"))
            result = freeze(plan, args.output).summary()
        else:
            manifest = materialize(
                args.registry,
                args.output,
                partitions=tuple(args.partitions),
                with_learning=args.with_learning,
                with_patients=args.with_patients,
                with_census=args.with_census,
                with_care=args.with_care,
                test_protocol=args.test_protocol,
            )
            result = {
                "worlds_generated": len(manifest["worlds"]),
                "test_access": manifest["test_access"],
            }
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"Cohort failed: {exc}\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
