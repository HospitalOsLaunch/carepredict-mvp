"""Zero-model-forward compatibility tests for integrated_full_model_v1."""
from __future__ import annotations

import ast
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_lab.integrated_full_model_v1_contract import (
    CHECKPOINT_SCHEMA,
    COMPONENTS,
    MODEL_SCHEMA,
    fingerprint,
    inspect_checkpoint,
    make_example_spec,
    validate_against_stage1,
    validate_checkpoint_manifest,
    validate_spec,
)

ROOT = Path(__file__).resolve().parents[1]


def _manifest(spec: dict[str, object], contents: bytes) -> dict[str, object]:
    return {
        "schema": CHECKPOINT_SCHEMA,
        "model_spec_sha256": fingerprint(spec),
        "weights_file": "weights.safetensors",
        "weights_sha256": hashlib.sha256(contents).hexdigest(),
        "components": list(COMPONENTS),
        "training_status": "UNTRAINED_ASSEMBLY",
        "source_commit": "a" * 40,
        "run_id": None,
        "approval_id": None,
        "synthetic_data_sha256": None,
        "generator_sha256": None,
        "normalization_sha256": None,
        "global_step": 0,
        "evidence": {
            "asof_dataset_verified": False, "independent_review": False
        },
    }


def test_contract_is_complete_and_deterministic() -> None:
    spec = make_example_spec()
    assert spec["schema"] == MODEL_SCHEMA
    assert spec["horizons_hours"] == [1, 6, 24]
    assert spec["action_features"] == ["staffing_delta", "discharge_delta"]
    assert spec["targets"][0]["name"] == "ed_waiting"
    assert spec["targets"][0]["definition"] != spec["targets"][1]["definition"]
    assert validate_spec(spec) == spec
    assert fingerprint(spec) == fingerprint(json.loads(json.dumps(spec)))
    assert spec["synthetic_only"] is True


@pytest.mark.parametrize(
    "section, mutation",
    [
        ("synthetic_only", False),
        ("source_interface", "SIH_REAL"),
        ("history_steps", 0),
        ("horizons_hours", [6, 1, 24]),
        ("horizons_hours", [1, 6, 6, 24]),
        ("horizons_hours", [1, -6, 24]),
        ("action_features", []),
        ("asof_contract", "EVENT_AT_ONLY"),
        ("action_policy", "ORACLE_FUTURE_ACTIONS"),
    ],
)
def test_invalid_contract_fail_closed(section: str, mutation: object) -> None:
    spec = make_example_spec()
    spec[section] = mutation
    with pytest.raises(ValueError):
        validate_spec(spec)


def test_hidden_source_and_missing_mask_rejected() -> None:
    spec = make_example_spec()
    spec["observation_features"][0]["source"] = "truth_future"
    with pytest.raises(ValueError, match="truth"):
        validate_spec(spec)
    spec = make_example_spec()
    spec["observation_features"] = [
        spec["observation_features"][0],
        spec["observation_features"][2],
    ]
    with pytest.raises(ValueError, match="missingness"):
        validate_spec(spec)


def test_stage1_dimensions_must_agree() -> None:
    spec = make_example_spec()
    stage1 = SimpleNamespace(
        latent_dim=128, rssm_deter_dim=256, rssm_stoch_dim=32,
        action_dim=2, encoder_max_steps=512,
    )
    validate_against_stage1(spec, stage1)
    stage1.action_dim = 3
    with pytest.raises(ValueError, match="Action"):
        validate_against_stage1(spec, stage1)


def test_untrained_checkpoint_manifest_has_no_model_claims() -> None:
    spec = make_example_spec()
    m = _manifest(spec, b"stand-in bytes, NOT real safetensors")
    assert validate_checkpoint_manifest(m, spec=spec) == m
    contaminated = deepcopy(m)
    contaminated["training_status"] = "SYNTHETIC_TRAINED_UNREVIEWED"
    with pytest.raises(ValueError, match="trained-checkpoint provenance"):
        validate_checkpoint_manifest(contaminated, spec=spec)
    contaminated = deepcopy(m)
    contaminated["global_step"] = 1
    with pytest.raises(ValueError, match="Untrained"):
        validate_checkpoint_manifest(contaminated, spec=spec)
    contaminated = deepcopy(m)
    contaminated["components"] = list(COMPONENTS[:-1])
    with pytest.raises(ValueError, match="all integrated"):
        validate_checkpoint_manifest(contaminated, spec=spec)


def test_checkpoint_inspection_is_metadata_only(tmp_path: Path) -> None:
    spec = make_example_spec()
    fake_weights = b"not a tensor container; hash inspection only"
    root = tmp_path / "checkpoint"
    root.mkdir()
    (root / "weights.safetensors").write_bytes(fake_weights)
    (root / "spec.json").write_text(json.dumps(spec))
    (root / "manifest.json").write_text(json.dumps(_manifest(spec, fake_weights)))
    receipt = inspect_checkpoint(root)
    assert receipt["status"] == "METADATA_HASHES_VERIFIED_NOT_MODEL_VALIDATED"
    assert receipt["model_forward"] is False
    assert receipt["training"] is False
    assert receipt["training_status"] == "UNTRAINED_ASSEMBLY"
    (root / "weights.safetensors").write_bytes(b"modified bytes")
    with pytest.raises(ValueError, match="manifest-committed"):
        inspect_checkpoint(root)


def test_source_assembly_structure_parse_only_without_torch_import() -> None:
    path = ROOT / "rs_jepa" / "integrated_full_model_v1.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    assert {"IntegratedFullModelV1", "MultiHorizonGaussianHead"} <= set(classes)
    model = classes["IntegratedFullModelV1"]
    methods = {node.name for node in model.body if isinstance(node, ast.FunctionDef)}
    assert {"forward", "update_ema_after_authorized_step", "_check_input"} <= methods
    module_funcs = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert {"save_untrained_assembly", "load_untrained_assembly"} <= module_funcs
