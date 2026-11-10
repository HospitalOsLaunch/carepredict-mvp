"""S0c — sealed synthetic-world registry and nonadaptive split planning.

Pure stdlib. No simulator, data content, model, tensor or training.
Never opens a reserved test archive. Only its *pre-approved metadata* may be
registered, with the blind partition kept inaccessible to experiment agents.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any, cast

SCHEMA = "hospitalos.synthetic_world_registry_v1"
SPLITS = ("train", "development", "validation", "ood_blind")
SHA = re.compile(r"^[0-9a-f]{64}$")
IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
FAMILIES = ("v041", "local_v1", "hybrid_v1")
OBSERVATION = ("v041", "site_v1")
FIELDS = {
    "world_id", "partition", "hospital_id", "generator_family",
    "observation_profile", "policy_family", "structure_family",
    "seed_group", "source_manifest_sha256", "observation_manifest_sha256",
    "action_manifest_sha256", "source_clock", "mechanism_tags",
    "readable_by_lab",
}
CLOCK = "fixed_utc_plus_01_no_dst"


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def validate_world(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != FIELDS:
        raise ValueError("World metadata fields must be complete and closed")
    for key in ("world_id", "hospital_id", "policy_family",
                "structure_family", "seed_group"):
        if not isinstance(raw[key], str) or not IDENT.fullmatch(raw[key]):
            raise ValueError(f"Invalid {key}")
    if raw["partition"] not in SPLITS:
        raise ValueError("Unrecognized synthetic partition")
    if raw["generator_family"] not in FAMILIES:
        raise ValueError("Unknown generator mechanism family")
    if raw["observation_profile"] not in OBSERVATION:
        raise ValueError("Unknown observation profile")
    if raw["source_clock"] != CLOCK:
        raise ValueError("Unexpected source clock")
    if (not isinstance(raw["mechanism_tags"], list)
            or not raw["mechanism_tags"]
            or any(not isinstance(t, str) or not IDENT.fullmatch(t)
                   for t in raw["mechanism_tags"])
            or len(set(raw["mechanism_tags"])) != len(raw["mechanism_tags"])):
        raise ValueError("Mechanism tags must be unique identifiers")
    for key in ("source_manifest_sha256", "observation_manifest_sha256",
                "action_manifest_sha256"):
        if not isinstance(raw[key], str) or not SHA.fullmatch(raw[key]):
            raise ValueError(f"Missing or invalid {key}")
    if type(raw["readable_by_lab"]) is not bool:
        raise ValueError("Readability must be explicit")
    if raw["partition"] == "ood_blind" and raw["readable_by_lab"]:
        raise PermissionError("Blind world cannot be readable by research agents")
    if raw["partition"] != "ood_blind" and not raw["readable_by_lab"]:
        raise ValueError("Development world must have a declared readable source")
    return cast(dict[str, Any], json.loads(_canonical(raw)))


def build_registry(
    worlds: list[dict[str, Any]], *,
    freeze_id: str,
    allow_dev_mechanism_overlap: bool = True,
) -> dict[str, Any]:
    """Validate metadata only. Does not inspect any dataset or holdout content."""
    if not isinstance(freeze_id, str) or not IDENT.fullmatch(freeze_id):
        raise ValueError("Frozen registry requires a stable freeze ID")
    if not isinstance(worlds, list) or len(worlds) < 4 or len(worlds) > 100000:
        raise ValueError("Need at least four separately identified worlds")
    records = [validate_world(w) for w in worlds]
    if len({r["world_id"] for r in records}) != len(records):
        raise ValueError("Duplicate world ID")
    if len({r["source_manifest_sha256"] for r in records}) != len(records):
        raise ValueError("Same source truth manifest appears in multiple partitions/worlds")
    if len({r["observation_manifest_sha256"] for r in records}) != len(records):
        raise ValueError("Observation archive reused")
    if len({r["action_manifest_sha256"] for r in records}) != len(records):
        raise ValueError("Action archive reused")
    by_partition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        by_partition[row["partition"]].append(row)
    if any(not by_partition[p] for p in SPLITS):
        raise ValueError("Train, development, validation and blind OOD all required")
    # Prevent the common error of reusing the same simulator random stream
    # under multiple world IDs. seed_group is a provenance *group*, not the
    # numeric seed alone: it must encode generator configuration and RNG lineage.
    seed_owners: dict[str, set[str]] = defaultdict(set)
    for row in records:
        seed_owners[row["seed_group"]].add(row["partition"])
    if any(len(parts) > 1 for parts in seed_owners.values()):
        raise ValueError("Seed lineage crosses split boundaries")
    # A structure may be repeated within train, but never in blind OOD.
    dev_structures = {
        row["structure_family"] for row in records if row["partition"] != "ood_blind"
    }
    blind_structures = {row["structure_family"] for row in by_partition["ood_blind"]}
    if dev_structures & blind_structures:
        raise ValueError("Blind OOD must hold out entire structure families")
    if not allow_dev_mechanism_overlap:
        dev_mechanisms = {
            (r["generator_family"], r["policy_family"])
            for r in records if r["partition"] in ("train", "development")
        }
        valid_mechanisms = {
            (r["generator_family"], r["policy_family"])
            for r in by_partition["validation"]
        }
        if dev_mechanisms & valid_mechanisms:
            raise ValueError("Validation mechanism is not independent")
    # Only non-blind records may be materialized into a training task.
    approved = sorted(
        (r for r in records if r["partition"] != "ood_blind"),
        key=lambda r: (SPLITS.index(r["partition"]), r["world_id"]),
    )
    blind = sorted(by_partition["ood_blind"], key=lambda r: r["world_id"])
    # Blind records are represented ONLY by commitments; never output a path,
    # seed, policy, structure or per-world metadata for adaptive research.
    blind_commitment = _hash(blind)
    result = {
        "schema": SCHEMA,
        "status": "FROZEN_METADATA_ONLY_NOT_DATA_CERTIFIED",
        "freeze_id": freeze_id,
        "readable_worlds": approved,
        "blind_world_count": len(blind),
        "blind_metadata_commitment_sha256": blind_commitment,
        "split_counts": {p: len(by_partition[p]) for p in SPLITS},
        "training_enabled": False,
        "reserved_holdout_opened": False,
        "synthetic_only": True,
    }
    result["registry_sha256"] = _hash(result)
    return result


def validate_job_scope(registry: dict[str, Any], world_ids: list[str],
                       purpose: str) -> dict[str, Any]:
    """Fail closed if an autonomous experiment selects a blind/validation world."""
    if registry.get("schema") != SCHEMA or registry.get("status") != (
        "FROZEN_METADATA_ONLY_NOT_DATA_CERTIFIED"
    ):
        raise ValueError("Unfrozen or unknown registry")
    if not isinstance(world_ids, list) or not world_ids:
        raise ValueError("At least one world must be selected")
    if len(world_ids) != len(set(world_ids)):
        raise ValueError("Duplicate world in experiment selection")
    if purpose not in ("train", "development_evaluation", "validation_once"):
        raise PermissionError("Unknown experiment purpose")
    allowed = {
        "train": {"train"},
        "development_evaluation": {"train", "development"},
        "validation_once": {"validation"},
    }[purpose]
    index = {w["world_id"]: w for w in registry["readable_worlds"]}
    if any(w not in index or index[w]["partition"] not in allowed for w in world_ids):
        raise PermissionError("World selection violates the frozen split policy")
    if purpose == "validation_once":
        # The validation-once permit is not issued by this helper.
        raise PermissionError("Validation opening needs a separate one-time signed permit")
    return {
        "status": "SCOPE_VALIDATED_NO_EXECUTION",
        "purpose": purpose,
        "world_ids": sorted(world_ids),
        "registry_sha256": registry["registry_sha256"],
        "training_authorized": False,
    }
