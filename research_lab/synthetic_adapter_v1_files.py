"""Read verified synthetic research exports without loading simulator or tensors.

Important: a same-run per-interval synthetic action export DOES NOT YET EXIST in
the operational adapter. This reader deliberately refuses to fabricate it.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

from .synthetic_adapter_v1 import ACTION_SCHEMA, V041_ACTIONS, build_window

OBSERVED_SCHEMA = "OPERATIONAL_V2_RESEARCH_1"
ALLOWED_PARTITIONS = frozenset(("train", "development", "validation"))
MAX_COMPRESSED_BYTES = 128 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_ROWS = 1_000_000


def _open_file(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("Only relative archive paths are allowed")
    root = root.resolve(strict=True)
    logical = root / relative
    if logical.is_symlink():
        raise ValueError("Symlinked archive source is forbidden")
    result = logical.resolve(strict=True)
    if not result.is_relative_to(root):
        raise ValueError("Archive path escapes its dataset directory")
    if not result.is_file():
        raise ValueError("Missing archive source")
    if result.stat().st_size > MAX_COMPRESSED_BYTES:
        raise ValueError("Archive source exceeds bounded read limit")
    return result


def _read_json(root: Path, relative: str) -> dict[str, Any]:
    path = _open_file(root, relative)
    if path.stat().st_size > 256 * 1024:
        raise ValueError("Metadata document exceeds expected size")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Metadata must be a JSON object")
    return value


def _hash_check(root: Path, relative: str, expected: Any) -> Path:
    if (not isinstance(expected, str) or len(expected) != 64
            or any(c not in "0123456789abcdef" for c in expected)):
        raise ValueError("Missing or malformed SHA256 evidence")
    path = _open_file(root, relative)
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError("Source bytes do not match immutable manifest")
    return path


def _jsonl_gz(path: Path) -> list[dict[str, Any]]:
    out = []
    count_bytes = 0
    with gzip.open(path, mode="rt", encoding="utf-8", newline="") as stream:
        for line in stream:
            count_bytes += len(line.encode("utf-8"))
            if count_bytes > MAX_UNCOMPRESSED_BYTES or len(out) >= MAX_ROWS:
                raise ValueError("Exceeded decompressed data size/row limit")
            if not line.strip():
                raise ValueError("Blank dataset record")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("Every dataset record must be an object")
            out.append(value)
    return out


def read_sources(
    observed_root: Path, action_root: Path, entity_id: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], str, dict[str, Any]]:
    """Verify both manifests and prove the observed/action source are same-run.

    Assumes source fingerprints identify the same underlying synthetic world.
    A matching string cannot prove a generator is scientifically realistic.
    """
    obs = _read_json(observed_root, "manifest.json")
    actions = _read_json(action_root, "manifest.json")
    partition = obs.get("partition")
    if partition not in ALLOWED_PARTITIONS:
        raise PermissionError("Reserved test or unknown partition is not readable")
    if (obs.get("schema_version") != OBSERVED_SCHEMA
            or obs.get("status") != "complete"
            or obs.get("synthetic_only") is not True
            or obs.get("data_role") != "operational_observations_no_targets"
            or obs.get("claims", {}).get("real_connector_validated") is not False):
        raise ValueError("Not a verified synthetic operational research export")
    mode = obs.get("modes", {}).get("hospital", {})
    if mode.get("path") != "observations/hospital.jsonl.gz":
        raise ValueError("Hospital observation frontier file unavailable")
    if entity_id not in mode.get("frontier", []):
        raise ValueError("Entity absent from declared hospital frontier")
    if (actions.get("schema") != ACTION_SCHEMA
            or actions.get("synthetic_only") is not True
            or actions.get("status") != "complete"
            or actions.get("partition") != partition
            or actions.get("source_manifest_sha256") != obs.get("source_manifest_sha256")
            or actions.get("source_clock") != obs.get("source_clock")
            or actions.get("entity_id") != entity_id
            or actions.get("entity_level") != "hospital"
            or actions.get("file") != "actions/intervals.jsonl.gz"):
        raise ValueError("Action ledger is not a compatible same-run synthetic export")
    source_sha = obs.get("source_manifest_sha256")
    if (not isinstance(source_sha, str) or len(source_sha) != 64
            or any(ch not in "0123456789abcdef" for ch in source_sha)):
        raise ValueError("Missing or invalid generator source SHA256 identity")
    o_hashes = obs.get("files_sha256", {})
    a_hashes = actions.get("files_sha256", {})
    o_path = _hash_check(
        observed_root, "observations/hospital.jsonl.gz",
        o_hashes.get("observations/hospital.jsonl.gz"),
    )
    _hash_check(observed_root, "topology.json", o_hashes.get("topology.json"))
    a_path = _hash_check(
        action_root, "actions/intervals.jsonl.gz",
        a_hashes.get("actions/intervals.jsonl.gz"),
    )
    provenance = {
        "observed_manifest_sha256": hashlib.sha256(
            _open_file(observed_root, "manifest.json").read_bytes()
        ).hexdigest(),
        "action_manifest_sha256": hashlib.sha256(
            _open_file(action_root, "manifest.json").read_bytes()
        ).hexdigest(),
        "shared_generator_manifest_sha256": obs["source_manifest_sha256"],
        "source_clock": obs.get("source_clock"),
        "action_coverage": actions.get("coverage"),
        "partition": partition,
        "same_run_asserted_by_export_manifests": True,
        "real_hospital_verified": False,
    }
    return (
        _jsonl_gz(o_path),
        _jsonl_gz(a_path),
        _read_json(observed_root, "topology.json"),
        partition,
        provenance,
    )


def build_from_archives(
    *,
    observed_root: Path, action_root: Path, entity_id: str,
    spec: dict[str, Any], origin: str, label_cutoff: str,
    max_age_hours: int,
    stage1: Any | None = None,
) -> dict[str, Any]:
    observations, actions, topology, partition, provenance = read_sources(
        observed_root, action_root, entity_id
    )
    s0b_receipt = None
    if spec.get("action_features") == list(V041_ACTIONS):
        if stage1 is None:
            raise ValueError(
                "Four-channel native actions require an explicit Stage1 configuration"
            )
        from .s0b_four_channel_bridge import verify_four_channel_binding

        s0b_receipt = verify_four_channel_binding(
            spec=spec, stage1=stage1, ledger=actions,
            coverage=provenance["action_coverage"],
            entity_id=entity_id, source_clock=provenance["source_clock"],
        )
    row = build_window(
        spec=spec, observations=observations, action_intervals=actions,
        topology=topology, entity_id=entity_id, origin=origin,
        label_cutoff=label_cutoff, partition=partition,
        max_age_hours=max_age_hours,
    )
    row["provenance"]["archives"] = provenance
    if s0b_receipt is not None:
        row["provenance"]["s0b_four_channel_binding"] = s0b_receipt
    return row
