"""Torch-free wire contract and checkpoint provenance for integrated_full_model_v1.

All functions in this module perform validation only. No model imports, ML
forward, training, data generation, or external calls.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

MODEL_SCHEMA = "hospitalos.integrated_full_model_v1"
CHECKPOINT_SCHEMA = "hospitalos.integrated_checkpoint_v1"
TARGET_UNITS = frozenset(("patients", "beds", "persons", "synthetic_minutes_per_hour"))
OBS_KIND = frozenset(("observed_value", "observation_mask", "observation_age", "calendar_known"))
COMPONENTS = ("encoder", "target_encoder", "rssm", "jepa_predictor", "forecast_head")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
SHA1 = re.compile(r"^[a-f0-9]{40}$")
IDENT = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
MAX_STRING = 512


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _names(items: list[dict[str, str]], *, key: str = "name") -> list[str]:
    return [item[key] for item in items]


def _ident(name: Any) -> bool:
    return isinstance(name, str) and IDENT.fullmatch(name) is not None


def validate_spec(raw: Any) -> dict[str, Any]:
    """Validate *exact* JSON shape and semantic compatibility, no torch import."""
    keys = {
        "schema", "synthetic_only", "source_interface", "history_steps",
        "step_hours", "horizons_hours", "observation_features", "static_features",
        "action_features", "targets", "latent_dim", "rssm_deter_dim",
        "rssm_stoch_dim", "head_hidden_dim", "asof_contract", "action_policy",
    }
    if not isinstance(raw, dict) or set(raw) != keys:
        raise ValueError("Unknown or missing integrated model spec fields")
    if raw["schema"] != MODEL_SCHEMA or raw["synthetic_only"] is not True:
        raise ValueError("Integrated v1 requires the synthetic-only schema")
    if raw["source_interface"] != "OPERATIONAL_V2_RESEARCH_1":
        raise ValueError("Unexpected as-of source interface")
    for name, minimum, maximum in (
        ("history_steps", 2, 2048),
        ("step_hours", 1, 24),
        ("latent_dim", 4, 4096),
        ("rssm_deter_dim", 4, 8192),
        ("rssm_stoch_dim", 2, 4096),
        ("head_hidden_dim", 4, 4096),
    ):
        n = raw[name]
        if type(n) is not int or not minimum <= n <= maximum:
            raise ValueError(f"Invalid integer dimension {name}")
    horizons = raw["horizons_hours"]
    if (not isinstance(horizons, list) or not horizons or len(horizons) > 20
            or any(type(x) is not int or x <= 0 or x > 720 for x in horizons)
            or sorted(set(horizons)) != horizons
            or any(x % raw["step_hours"] for x in horizons)):
        raise ValueError("Horizons must be unique, positive and aligned with step size")
    features = raw["observation_features"]
    if not isinstance(features, list) or not 1 <= len(features) <= 256:
        raise ValueError("Missing observable feature list")
    for entry in features:
        if (not isinstance(entry, dict) or set(entry) != {"name", "kind", "source"}
                or not _ident(entry["name"]) or entry["kind"] not in OBS_KIND
                or not _ident(entry["source"])):
            raise ValueError("Invalid observable feature or provenance tag")
        if entry["source"].startswith(("truth", "hidden", "future", "oracle")):
            raise ValueError("Simulator truth/hidden features are forbidden")
    if len(set(_names(features))) != len(features):
        raise ValueError("Duplicate observation feature name")
    if not any(x["kind"] == "observation_mask" for x in features):
        raise ValueError("Explicit missingness mask required")
    for name in ("static_features", "action_features"):
        values = raw[name]
        if (not isinstance(values, list) or len(values) > 128
                or any(not _ident(x) for x in values)
                or len(set(values)) != len(values)):
            raise ValueError(f"Invalid {name}")
    if not raw["action_features"]:
        raise ValueError("Action-conditioned RSSM requires explicit action channels")
    if raw["action_features"] != ["staffing_delta", "discharge_delta"]:
        raise ValueError(
            "Integrated v1 accepts only the existing RS-JEPA synthetic action order; "
            "a separate approved adapter is required for operational actions"
        )
    targets = raw["targets"]
    if not isinstance(targets, list) or not 1 <= len(targets) <= 32:
        raise ValueError("No forecast targets")
    for target in targets:
        if (not isinstance(target, dict)
                or set(target) != {"name", "unit", "level", "definition"}
                or not _ident(target["name"])
                or target["unit"] not in TARGET_UNITS
                or target["level"] not in ("unit", "pole", "hospital", "ght")
                or not isinstance(target["definition"], str)
                or not 12 <= len(target["definition"]) <= MAX_STRING):
            raise ValueError("Target needs name, unit, level and physical definition")
    if len(set(_names(targets))) != len(targets):
        raise ValueError("Duplicate forecast target name")
    if raw["asof_contract"] != "VERSIONED_AVAILABLE_AT_PER_SOURCE":
        raise ValueError("As-of source versions are mandatory")
    if raw["action_policy"] != "EXPLICIT_KNOWN_PLAN_OR_COUNTERFACTUAL":
        raise ValueError("Future actions must never be silently sourced from future facts")
    return json.loads(canonical_bytes(raw))


def validate_against_stage1(spec: dict[str, Any], stage1: Any) -> None:
    """Compare spec to existing RS-JEPA Stage1Config using duck-typed attributes."""
    validate_spec(spec)
    expected = {
        "latent_dim": stage1.latent_dim,
        "rssm_deter_dim": stage1.rssm_deter_dim,
        "rssm_stoch_dim": stage1.rssm_stoch_dim,
    }
    for name, value in expected.items():
        if spec[name] != value:
            raise ValueError(f"{name} differs from existing RS-JEPA configuration")
    if len(spec["action_features"]) != stage1.action_dim:
        raise ValueError("Action channels differ from RS-JEPA action_dim")
    if spec["history_steps"] > stage1.encoder_max_steps:
        raise ValueError("History exceeds encoder positional span")


def validate_checkpoint_manifest(raw: Any, *, spec: dict[str, Any]) -> dict[str, Any]:
    """Check metadata; never deserialize tensors or claim learned-weight validity."""
    validate_spec(spec)
    fields = {
        "schema", "model_spec_sha256", "weights_file", "weights_sha256",
        "components", "training_status", "source_commit", "run_id",
        "approval_id", "synthetic_data_sha256", "generator_sha256",
        "normalization_sha256", "global_step", "evidence",
    }
    if not isinstance(raw, dict) or set(raw) != fields:
        raise ValueError("Malformed checkpoint manifest")
    if raw["schema"] != CHECKPOINT_SCHEMA:
        raise ValueError("Unknown checkpoint format")
    if raw["model_spec_sha256"] != fingerprint(spec):
        raise ValueError("Checkpoint model spec fingerprint mismatch")
    if raw["weights_file"] != "weights.safetensors":
        raise ValueError("Unsafe or unexpected checkpoint tensor format")
    if not SHA256.fullmatch(str(raw["weights_sha256"])):
        raise ValueError("Checkpoint weights hash invalid")
    if raw["components"] != list(COMPONENTS):
        raise ValueError("Checkpoint does not describe all integrated components")
    if raw["training_status"] not in (
        "UNTRAINED_ASSEMBLY", "SYNTHETIC_TRAINED_UNREVIEWED",
        "SYNTHETIC_EVALUATED_NO_PROMOTION",
    ):
        raise ValueError("Unknown checkpoint scientific status")
    if not SHA1.fullmatch(str(raw["source_commit"])):
        raise ValueError("Source revision not pinned")
    if type(raw["global_step"]) is not int or raw["global_step"] < 0:
        raise ValueError("Invalid training step")
    if (not isinstance(raw["evidence"], dict)
            or set(raw["evidence"]) != {"asof_dataset_verified", "independent_review"}):
        raise ValueError("Evidence must declare review and source status explicitly")
    if type(raw["evidence"]["asof_dataset_verified"]) is not bool:
        raise ValueError("Invalid as-of evidence state")
    if type(raw["evidence"]["independent_review"]) is not bool:
        raise ValueError("Invalid review state")
    if raw["training_status"] != "UNTRAINED_ASSEMBLY":
        for name in ("run_id", "approval_id", "synthetic_data_sha256",
                     "generator_sha256", "normalization_sha256"):
            if not isinstance(raw[name], str) or not raw[name]:
                raise ValueError(f"Missing trained-checkpoint provenance {name}")
        for name in ("synthetic_data_sha256", "generator_sha256",
                     "normalization_sha256"):
            if not SHA256.fullmatch(raw[name]):
                raise ValueError(f"Invalid hash {name}")
        if raw["global_step"] == 0:
            raise ValueError("Trained checkpoint cannot have zero steps")
    elif (raw["global_step"] != 0 or any(raw[name] is not None for name in (
            "run_id", "approval_id", "synthetic_data_sha256", "generator_sha256",
            "normalization_sha256"))
          or any(raw["evidence"].values())):
        raise ValueError("Untrained assembly cannot claim training or independent evidence")
    if raw["training_status"] == "SYNTHETIC_EVALUATED_NO_PROMOTION":
        if not all(raw["evidence"].values()):
            raise ValueError("Evaluated status needs independent source and review evidence")
    return json.loads(canonical_bytes(raw))


def inspect_checkpoint(directory: Path) -> dict[str, Any]:
    """Non-executing receipt; validates hashes only, NEVER loads weights."""
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("Checkpoint must be a real directory")
    spec_file = directory / "spec.json"
    meta_file = directory / "manifest.json"
    weights_file = directory / "weights.safetensors"
    for f in (spec_file, meta_file, weights_file):
        if f.is_symlink() or not f.is_file():
            raise ValueError("Missing or symlinked checkpoint component")
    spec = validate_spec(json.loads(spec_file.read_text(encoding="utf-8")))
    meta = validate_checkpoint_manifest(
        json.loads(meta_file.read_text(encoding="utf-8")), spec=spec
    )
    if hashlib.sha256(weights_file.read_bytes()).hexdigest() != meta["weights_sha256"]:
        raise ValueError("Checkpoint tensor bytes are not the manifest-committed bytes")
    return {
        "status": "METADATA_HASHES_VERIFIED_NOT_MODEL_VALIDATED",
        "model_schema": MODEL_SCHEMA,
        "training_status": meta["training_status"],
        "components": meta["components"],
        "spec_sha256": fingerprint(spec),
        "model_forward": False,
        "training": False,
        "evidence": meta["evidence"],
    }


def make_example_spec() -> dict[str, Any]:
    """A fixture schema, not a hospital-approved scientific or dataset contract."""
    return validate_spec({
        "schema": MODEL_SCHEMA,
        "synthetic_only": True,
        "source_interface": "OPERATIONAL_V2_RESEARCH_1",
        "history_steps": 168,
        "step_hours": 1,
        "horizons_hours": [1, 6, 24],
        "observation_features": [
            {"name": "ed_waiting_observed", "kind": "observed_value",
             "source": "operational_observed"},
            {"name": "ed_waiting_missing", "kind": "observation_mask",
             "source": "observed_mask"},
            {"name": "ed_waiting_age_hours", "kind": "observation_age",
             "source": "observed_age"},
        ],
        "static_features": ["bed_capacity"],
        "action_features": ["staffing_delta", "discharge_delta"],
        "targets": [
            {"name": "ed_waiting", "unit": "patients", "level": "hospital",
             "definition": "Demande de placement en lit depuis les urgences pour ce périmètre."},
            {"name": "occupancy", "unit": "patients", "level": "hospital",
             "definition": "Patients présents dans le périmètre, stock à l'heure visée."},
        ],
        "latent_dim": 128,
        "rssm_deter_dim": 256,
        "rssm_stoch_dim": 32,
        "head_hidden_dim": 128,
        "asof_contract": "VERSIONED_AVAILABLE_AT_PER_SOURCE",
        "action_policy": "EXPLICIT_KNOWN_PLAN_OR_COUNTERFACTUAL",
    })
