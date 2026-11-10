"""S0d data-lineage and as-of audit for one accessible synthetic world.

Reads existing synthetic-only archives but NEVER invokes the simulator, PyTorch,
model inference, optimizer or a GPU. Does NOT open validation or blind test.
The result is an audit receipt, not permission to fit a world model.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from .integrated_full_model_v1_contract import fingerprint, validate_spec
from .s0b_four_channel_bridge import verify_four_channel_binding
from .s0c_world_registry import SCHEMA as REGISTRY_SCHEMA
from .s0c_world_registry import validate_job_scope
from .synthetic_adapter_v1 import V041_ACTIONS, build_window, instant
from .synthetic_adapter_v1_files import read_sources

SCHEMA = "hospitalos.s0d_source_readiness_v1"
MAX_ORIGINS = 64
MAX_MANIFEST_BYTES = 262_144
MAX_SOURCE_BYTES = 128 * 1024 * 1024


def _sha_file(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def _regular(root: Path, rel: str) -> Path:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Archive root must be a regular directory")
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute():
        raise ValueError("Absolute or empty archive paths are forbidden")
    logical = root / rel
    if any(piece in (".", "..") for piece in Path(rel).parts):
        raise ValueError("Archive path cannot traverse directories")
    if logical.is_symlink() or not logical.is_file():
        raise ValueError("Missing or symlinked source file")
    resolved = logical.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve(strict=True)):
        raise ValueError("Archive file escapes source root")
    if resolved.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError("Source file exceeds bounded audit limit")
    return resolved


def _metadata(root: Path, file: str = "manifest.json") -> tuple[dict[str, Any], str]:
    path = _regular(root, file)
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("Source metadata exceeds bound")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Source metadata must be a mapping")
    return cast(dict[str, Any], raw), _sha_file(path)


def _registry_world(registry: dict[str, Any], world_id: str) -> dict[str, Any]:
    if registry.get("schema") != REGISTRY_SCHEMA:
        raise ValueError("Unknown sealed world registry")
    committed = registry.get("registry_sha256")
    canonical = {k: v for k, v in registry.items() if k != "registry_sha256"}
    current = hashlib.sha256(json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")).hexdigest()
    if committed != current:
        raise ValueError("Sealed registry metadata was modified")
    # Never read a validation/holdout root; scope check precedes all paths.
    validate_job_scope(registry, [world_id], "development_evaluation")
    matching = [row for row in registry["readable_worlds"] if row["world_id"] == world_id]
    if len(matching) != 1 or matching[0]["partition"] not in ("train", "development"):
        raise PermissionError("S0d can audit only train/development worlds")
    return cast(dict[str, Any], matching[0])


def _source_match(
    row: dict[str, Any], truth_root: Path,
    observed: dict[str, Any], actions: dict[str, Any],
) -> tuple[dict[str, Any], dt.datetime, dt.datetime, dict[str, str]]:
    truth, truth_sha = _metadata(truth_root)
    config, _config_file_sha = _metadata(truth_root, "config.json")
    if (truth_sha != row["source_manifest_sha256"]
            or truth.get("status") != "complete"
            or truth.get("synthetic_only") is not True
            or truth.get("data_role") != "simulation_truth_not_training_inputs"
            or truth.get("partition") != row["partition"]
            or truth.get("hospital_id") != row["hospital_id"]
            or truth.get("mechanism_family") != row["generator_family"]):
        raise ValueError("Frozen world source does not match S0c registry")
    if (config.get("partition") != row["partition"]
            or config.get("hospital_id") != row["hospital_id"]
            or config.get("mechanism_family") != row["generator_family"]
            or config.get("observation", {}).get("mode") != row["observation_profile"]):
        raise ValueError("Source configuration identity and observation profile mismatch")
    if (observed.get("source_manifest_sha256") != truth_sha
            or actions.get("source_manifest_sha256") != truth_sha
            or observed.get("partition") != row["partition"]
            or actions.get("partition") != row["partition"]
            or observed.get("hospital_id") != row["hospital_id"]
            or actions.get("entity_id") != row["hospital_id"]
            or observed.get("source_clock") != row["source_clock"]
            or actions.get("source_clock") != row["source_clock"]):
        raise ValueError("Source, observation and action archives do not share one run")
    expected_files = truth.get("files_sha256")
    if not isinstance(expected_files, dict):
        raise ValueError("Missing source-file hashes")
    for name in ("config.json", "truth/events.jsonl.gz", "truth/units_hourly.csv"):
        if _sha_file(_regular(truth_root, name)) != expected_files.get(name):
            raise ValueError(f"Source truth bytes not verified: {name}")
    action_source_files = actions.get("source_files_sha256", {})
    if action_source_files and (
        action_source_files.get("config.json") != expected_files.get("config.json")
        or action_source_files.get("truth/events.jsonl.gz") != (
            expected_files.get("truth/events.jsonl.gz")
        )
    ):
        raise ValueError("Action exporter declares different source truth files")
    days = config.get("days")
    if type(days) is not int or not 0 < days <= 366:
        raise ValueError("Invalid source simulation duration")
    start = dt.datetime.combine(
        dt.date.fromisoformat(config["start"]), dt.time(),
        tzinfo=dt.timezone(dt.timedelta(hours=1)),
    ).astimezone(dt.UTC)
    end = start + days * dt.timedelta(days=1)
    if (instant(observed["start"]) != start
            or instant(observed["end_exclusive"]) != end):
        raise ValueError("Observation export boundary differs from source configuration")
    hashes = {
        "source": truth_sha,
        "observations": row["observation_manifest_sha256"],
        "actions": row["action_manifest_sha256"],
    }
    return config, start, end, hashes


def _overlap_pairs(intervals: list[tuple[dt.datetime, dt.datetime]]) -> int:
    """Report correlated source windows, never silently assert independence."""
    count = 0
    for index, (start, end) in enumerate(intervals):
        for other_start, other_end in intervals[index + 1:]:
            if start <= other_end and other_start <= end:
                count += 1
    return count


def audit_world(
    *, registry: dict[str, Any], world_id: str,
    truth_root: Path, observed_root: Path, action_root: Path,
    spec: dict[str, Any], origins: list[str], label_cutoff: str,
    max_age_hours: int, encoder_max_steps: int = 512,
) -> dict[str, Any]:
    """Read ONLY train/dev worlds. Validate as-of windows and lineage metadata."""
    row = _registry_world(registry, world_id)  # Before touching any archive paths
    spec = validate_spec(spec)
    if spec["action_features"] != list(V041_ACTIONS):
        raise ValueError("S0d presently audits only native four-channel V0.4.1 actions")
    if (not isinstance(origins, list) or not 1 <= len(origins) <= MAX_ORIGINS
            or any(not isinstance(value, str) for value in origins)):
        raise ValueError("1–64 explicit decision origins required")
    timestamps = [instant(value) for value in origins]
    if len(set(timestamps)) != len(timestamps):
        raise ValueError("Duplicate origin would double-count evidence")
    if type(encoder_max_steps) is not int or not 1 <= encoder_max_steps <= 2048:
        raise ValueError("Invalid declared encoder positional length")
    L = instant(label_cutoff)

    observed_meta, observed_sha = _metadata(observed_root)
    actions_meta, actions_sha = _metadata(action_root)
    if observed_sha != row["observation_manifest_sha256"]:
        raise ValueError("Actual observation manifest SHA differs from S0c commitment")
    if actions_sha != row["action_manifest_sha256"]:
        raise ValueError("Actual action manifest SHA differs from S0c commitment")
    _config, source_start, source_end, hashes = _source_match(
        row, truth_root, observed_meta, actions_meta
    )
    observed_rows, action_rows, topology, partition, provenance = read_sources(
        observed_root, action_root, row["hospital_id"]
    )
    if partition != row["partition"]:
        raise ValueError("Partition changed after source-verification")

    # Stage1Signature is a dimension-only contract, not a constructed torch model.
    signature = SimpleNamespace(
        action_dim=4, latent_dim=spec["latent_dim"],
        rssm_deter_dim=spec["rssm_deter_dim"],
        rssm_stoch_dim=spec["rssm_stoch_dim"],
        encoder_max_steps=encoder_max_steps,
    )
    action_receipt = verify_four_channel_binding(
        spec=spec, stage1=signature, ledger=action_rows,
        coverage=actions_meta.get("coverage"),
        entity_id=row["hospital_id"],
        source_clock=row["source_clock"],
    )
    H = dt.timedelta(hours=max(spec["horizons_hours"]))
    history = dt.timedelta(hours=(spec["history_steps"] - 1) * spec["step_hours"])
    frames = []
    present = 0
    total = 0
    missing_features = 0
    latest_known_action = None
    for D in sorted(timestamps):
        if D - history < source_start or D + H > source_end:
            raise ValueError("Context or forecast target crosses source simulation boundary")
        if L < D + H or L > source_end:
            raise ValueError("Labels not matured inside source extraction interval")
        sample = build_window(
            spec=spec, observations=observed_rows, action_intervals=action_rows,
            topology=topology, entity_id=row["hospital_id"],
            origin=D.isoformat(), label_cutoff=L.isoformat(),
            partition=partition, max_age_hours=max_age_hours,
        )
        if (not sample["supervision_alignment"]["training_loss_authorized"] is False
                or sample["action_mode"] != "no_op"
                or sample["forward_executed"] is not False):
            raise ValueError("Source window misrepresented training permission or action mode")
        if any(t > sample["origin_ns"][0]
               for t in sample["available_ns"][0] + sample["action_available_ns"][0]):
            raise ValueError("Window contains observations/actions unavailable at D")
        masks = sample["training_target_mask"][0]
        present += sum(sum(row_) for row_ in masks)
        total += sum(len(row_) for row_ in masks)
        missing_features += sample["provenance"]["missing_feature_values"]
        latest_known_action = max(sample["action_available_ns"][0])
        frames.append((D - history, D + H))
    return {
        "schema": SCHEMA,
        "status": "SOURCE_PREFIXES_CHECKED_NOT_TRAINING_ELIGIBLE",
        "world_id": world_id,
        "partition": row["partition"],
        "source_manifest_hashes": hashes,
        "model_spec_sha256": fingerprint(spec),
        "asof_windows_checked": len(frames),
        "correlated_window_pairs": _overlap_pairs(frames),
        "missing_observation_features": missing_features,
        "future_labels_present": present,
        "future_label_slots": total,
        "historical_actions_last_available_ns": latest_known_action,
        "native_action_coverage": {
            "hour_intervals": action_receipt["hour_intervals_checked"],
            "decision_events": action_receipt["decision_events_claimed"],
            "units": action_receipt["n_units"],
        },
        "source_clock": row["source_clock"],
        "synthetic_only": True,
        "future_factual_labels_compatible_with_no_op": False,
        "trainable_supervision_verified": False,
        "model_forward": False,
        "training": False,
        "simulation": False,
        "blind_holdout_opened": False,
        "legacy_checkpoints_promoted": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit one accessible S0c synthetic world")
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--world-id", required=True)
    parser.add_argument("--truth", required=True, type=Path)
    parser.add_argument("--observed", required=True, type=Path)
    parser.add_argument("--actions", required=True, type=Path)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--origin", required=True, action="append")
    parser.add_argument("--label-cutoff", required=True)
    parser.add_argument("--max-age-hours", type=int, default=6)
    parser.add_argument("--encoder-max-steps", type=int, default=512)
    args = parser.parse_args(argv)
    # No auto-discovery of reserved worlds. Roots must be explicitly supplied.
    receipt = audit_world(
        registry=json.loads(args.registry.read_text(encoding="utf-8")),
        world_id=args.world_id, truth_root=args.truth,
        observed_root=args.observed, action_root=args.actions,
        spec=json.loads(args.spec.read_text(encoding="utf-8")),
        origins=args.origin, label_cutoff=args.label_cutoff,
        max_age_hours=args.max_age_hours,
        encoder_max_steps=args.encoder_max_steps,
    )
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
