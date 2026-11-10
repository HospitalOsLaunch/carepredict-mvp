"""S0c: freeze a guarded, metadata-only synthetic pretraining exposure registry.

This control plane does not generate worlds, read trajectories, load model weights,
forward models, train, query APIs, or access holdout test trajectories.

A trusted freezer reads the *existing canonical* cohort registry once, then emits
a redacted index for a lower-privilege worker. Reserved test identifiers and
configurations are never copied into that worker-facing index.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from .integrated_full_model_v1_contract import fingerprint, validate_spec

SCHEMA = "hospitalos.synthetic_pretraining_registry_s0c_v1"
AXES = {
    "structure", "mechanism", "arrivals", "discharges", "staffing",
    "staff_forecasts", "downstream_confirmation",
}
DATA_AXES = {"arrivals", "discharges", "staffing"}
DOC_AXES = {"staff_forecasts", "downstream_confirmation"}
MAX_BYTES = 20 * 1024 * 1024


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_BYTES:
        raise ValueError("Missing, symlinked or oversized registry metadata")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected a metadata JSON object")
    return value


def _axis_value(config: dict[str, Any], axis: str, structure: str) -> str:
    if axis == "structure":
        return structure
    if axis == "mechanism":
        return str(config["mechanism_family"])
    if axis in DATA_AXES:
        return str(config["dynamics"][axis])
    if axis in DOC_AXES:
        return str(config["documentary"][axis])
    raise ValueError("Unexpected held-out axis")


def _range(first: int, last: int, *, days: int, history: int, horizon: int) -> dict[str, int]:
    if first < history or last > days * 24 - horizon or first > last:
        raise ValueError("Empty or leaking origin range")
    return {"first_origin_h": first, "last_origin_h": last}


def compile_index(
    registry: dict[str, Any], *, model_spec: dict[str, Any],
    temporal_dev_days: int, embargo_hours: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split whole hospitals first, then embargo time within train-only worlds.

    The input must originate from hospitalos.synthetic.cohort.load_registry
    in production. Tests may pass miniature in-memory fixtures; such tests
    never qualify actual source authenticity.
    """
    spec = validate_spec(model_spec)
    plan = registry.get("plan")
    worlds = registry.get("worlds")
    if not isinstance(plan, dict) or not isinstance(worlds, list) or not worlds:
        raise ValueError("Invalid canonical registry data shape")
    if registry.get("schema_version") != "0.1":
        raise ValueError("Unexpected upstream registry schema")
    axis = plan.get("split_axis")
    if axis not in AXES:
        raise ValueError("Unsupported holdout axis")
    if (type(temporal_dev_days) is not int or not 1 <= temporal_dev_days <= 90
            or type(embargo_hours) is not int or not 0 <= embargo_hours <= 720):
        raise ValueError("Invalid frozen temporal holdout or embargo")
    if spec["step_hours"] != 1:
        raise ValueError("S0c requires hourly operational source grid")
    history = spec["history_steps"]
    horizon = max(spec["horizons_hours"])
    entries: dict[str, list[dict[str, Any]]] = {
        "train": [], "development_temporal": [], "development_ood": [],
    }
    seen_worlds: set[str] = set()
    seen_seeds: set[int] = set()
    hospital_owners: dict[str, str] = {}
    axis_owners: dict[str, str] = {}
    config_hashes: dict[str, str] = {}
    reserved_count = 0
    for world in worlds:
        if not isinstance(world, dict):
            raise ValueError("Invalid world entry")
        config = world.get("config")
        if not isinstance(config, dict):
            raise ValueError("Missing world configuration")
        partition = config.get("partition")
        if partition not in ("train", "validation", "test"):
            raise ValueError("Unexpected canonical world partition")
        wid = world.get("world_id")
        hospital = config.get("hospital_id")
        structure = world.get("structure_sha256")
        seed = config.get("seed")
        if (not isinstance(wid, str) or not wid or wid in seen_worlds
                or not isinstance(hospital, str) or not hospital
                or not isinstance(structure, str) or len(structure) != 64
                or type(seed) is not int or seed in seen_seeds):
            raise ValueError("World identities, structural hash or seeds invalid")
        seen_worlds.add(wid)
        seen_seeds.add(seed)
        old_partition = hospital_owners.setdefault(hospital, partition)
        if old_partition != partition:
            raise ValueError("Hospital identity crosses partitions")
        value = _axis_value(config, axis, structure)
        if axis_owners.setdefault(value, partition) != partition:
            raise ValueError("Held-out generative axis crosses partitions")
        days = config.get("days")
        if type(days) is not int or days <= 0 or days > 366:
            raise ValueError("Invalid historical length")
        if partition == "test":
            reserved_count += 1
            continue  # Never copy reserved world IDs, seeds or parameter variants.
        config_hash = fingerprint(config)
        if wid in config_hashes and config_hashes[wid] != config_hash:
            raise ValueError("Conflicting world configuration")
        config_hashes[wid] = config_hash
        base = {
            "world_id": wid,
            "hospital_id": hospital,
            "replicate": world.get("replicate"),
            "seed": seed,
            "structure_sha256": structure,
            "config_content_sha256": config_hash,
            "heldout_axis": axis,
            "heldout_axis_value": value,
            "mechanism_family": config["mechanism_family"],
            "days": days,
            "observation_profile_sha256": fingerprint(config.get("observation", {})),
            "data_role": "metadata_only_no_trajectories",
        }
        if type(base["replicate"]) is not int or base["replicate"] < 0:
            raise ValueError("Invalid replicate")
        latest = days * 24 - horizon
        if partition == "validation":
            entries["development_ood"].append({
                **base, "origin_hours": _range(
                    history, latest, days=days, history=history, horizon=horizon
                ),
            })
        else:
            # Strict nonoverlap of [origin-history+1, origin+horizon] footprints.
            dev_start = days * 24 - temporal_dev_days * 24
            train_end = dev_start - history - horizon - embargo_hours
            entries["train"].append({
                **base, "origin_hours": _range(
                    history, train_end, days=days, history=history, horizon=horizon
                ),
            })
            entries["development_temporal"].append({
                **base, "origin_hours": _range(
                    dev_start, latest, days=days, history=history, horizon=horizon
                ),
            })
    if not all(entries.values()) or reserved_count < 1:
        raise ValueError("Train, temporal dev, OOD dev and reserved test are mandatory")
    if any(e["hospital_id"] in {
        t["hospital_id"] for t in entries["train"]
    } for e in entries["development_ood"]):
        raise ValueError("OOD hospital cannot enter training")
    for kind in entries:
        entries[kind].sort(key=lambda x: x["world_id"])
    index = {
        "schema": SCHEMA,
        "synthetic_only": True,
        "model_spec_sha256": fingerprint(spec),
        "split_axis": axis,
        "policy": {
            "history_steps": history,
            "max_horizon_hours": horizon,
            "temporal_dev_days": temporal_dev_days,
            "embargo_hours": embargo_hours,
            "temporal_split_footprints_disjoint": True,
            "ood_axis_disjoint_from_train": True,
            "reserved_test_excluded": True,
        },
        "partitions": entries,
        "training_allowed": False,
        "model_forward": False,
        "simulation": False,
    }
    summary = {
        "train_worlds": len(entries["train"]),
        "development_temporal_worlds": len(entries["development_temporal"]),
        "development_ood_worlds": len(entries["development_ood"]),
        "reserved_test_world_count": reserved_count,
        "test_trajectories_read": False,
        "source_worlds_total": len(worlds),
    }
    return index, summary


def freeze(
    registry_root: Path, model_spec_file: Path, output: Path, *,
    temporal_dev_days: int, embargo_hours: int,
) -> dict[str, Any]:
    """Official upstream validation before publishing a sanitized, read-only index."""
    if output.exists():
        raise FileExistsError("S0c exposure registry is immutable")
    if registry_root.is_symlink() or not registry_root.is_dir():
        raise ValueError("Frozen cohort source must be an actual directory")
    source = registry_root.resolve()
    target = output.resolve()
    if target.is_relative_to(source):
        raise ValueError("Cannot write inside canonical registry source")
    manifest_path = source / "manifest.json"
    registry_path = source / "registry.json"
    manifest = _json(manifest_path)
    if (manifest.get("status") != "frozen"
            or manifest.get("synthetic_only") is not True
            or manifest.get("data_role") != "cohort_registry_no_trajectories"
            or manifest.get("files_sha256") != {"registry.json": _sha(registry_path)}):
        raise ValueError("Upstream manifest or registry bytes failed validation")

    # The official source validator also checks the deterministic plan, structural
    # clones, seed collisions, runtime and generation code version fingerprint.
    # Import only when explicitly freezing an official source (not in smoke tests).
    from hospitalos.synthetic.cohort import load_registry

    verified = load_registry(source)
    raw = verified.model_dump(mode="json")
    if verified.fingerprint != manifest["registry_sha256"]:
        raise ValueError("Canonical registry fingerprint differs from manifest")
    spec = validate_spec(_json(model_spec_file))
    index, summary = compile_index(
        raw, model_spec=spec,
        temporal_dev_days=temporal_dev_days, embargo_hours=embargo_hours,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".s0c-", dir=output.parent) as temp:
        staging = Path(temp) / "exposure"
        staging.mkdir()
        index_file = staging / "index.json"
        index_file.write_text(
            json.dumps(index, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        result = {
            "schema": SCHEMA,
            "status": "EXPOSURE_METADATA_ONLY_NO_TRAINING",
            "synthetic_only": True,
            "upstream_registry_sha256": verified.fingerprint,
            "upstream_manifest_sha256": _sha(manifest_path),
            "model_spec_sha256": fingerprint(spec),
            "index_sha256": _sha(index_file),
            "summary": summary,
            "holdout_status": "TEST_TRAJECTORIES_UNOPENED",
            "model_forward": False,
            "training": False,
            "simulation": False,
        }
        (staging / "manifest.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        staging.rename(output)
    return result


def inspect(output: Path) -> dict[str, Any]:
    """Lower-privilege worker may inspect only the sanitized S0c directory."""
    if not output.is_dir() or output.is_symlink():
        raise ValueError("S0c index directory missing")
    manifest = _json(output / "manifest.json")
    index_file = output / "index.json"
    index = _json(index_file)
    if (manifest.get("schema") != SCHEMA or index.get("schema") != SCHEMA
            or manifest.get("status") != "EXPOSURE_METADATA_ONLY_NO_TRAINING"
            or manifest.get("holdout_status") != "TEST_TRAJECTORIES_UNOPENED"
            or manifest.get("index_sha256") != _sha(index_file)
            or manifest.get("model_spec_sha256") != index.get("model_spec_sha256")
            or index.get("training_allowed") is not False
            or index.get("simulation") is not False):
        raise ValueError("Corrupt or unauthorized S0c index")
    entries = index.get("partitions")
    if not isinstance(entries, dict) or set(entries) != {
        "train", "development_temporal", "development_ood"
    }:
        raise ValueError("Unexpected test or unknown partition in worker index")
    all_ids: dict[str, str] = {}
    for partition, worlds in entries.items():
        if not isinstance(worlds, list) or not worlds:
            raise ValueError("Empty S0c partition")
        for world in worlds:
            if not isinstance(world, dict) or "origin_hours" not in world:
                raise ValueError("Invalid worker world entry")
            owner = all_ids.setdefault(world["world_id"], partition)
            if owner != partition and {
                owner, partition
            } != {"train", "development_temporal"}:
                raise ValueError("World reused across OOD/training partitions")
    return {
        "status": "S0C_METADATA_HASH_VERIFIED_NO_HOLDOUT_ACCESS",
        "summary": manifest["summary"],
        "index_sha256": manifest["index_sha256"],
        "model_spec_sha256": manifest["model_spec_sha256"],
        "training": False,
        "model_forward": False,
        "simulation": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="S0c synthetic data exposure registry")
    cmd = parser.add_subparsers(dest="command", required=True)
    create = cmd.add_parser("freeze")
    create.add_argument("--canonical-registry", type=Path, required=True)
    create.add_argument("--model-spec", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--temporal-dev-days", type=int, default=28)
    create.add_argument("--embargo-hours", type=int, default=24)
    check = cmd.add_parser("inspect")
    check.add_argument("--index", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "freeze":
            report = freeze(
                args.canonical_registry, args.model_spec, args.output,
                temporal_dev_days=args.temporal_dev_days,
                embargo_hours=args.embargo_hours,
            )
        else:
            report = inspect(args.index)
    except (ValueError, OSError, KeyError, ImportError) as exc:
        parser.exit(2, f"REFUSED: {type(exc).__name__}: {exc}\n")
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
