"""S0c metadata-only registry tests; no simulator, torch, or trajectory reads."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from research_lab.integrated_full_model_v1_contract import make_v041_synthetic_spec
from research_lab.s0c_synthetic_registry import (
    SCHEMA,
    compile_index,
    inspect,
)


def fixture() -> dict[str, Any]:
    def world(name: str, hospital: str, partition: str,
              shape: str, seed: int) -> dict[str, Any]:
        return {
            "world_id": name,
            "structure_id": "S_" + partition.upper(),
            "structure_sha256": shape * 64,
            "replicate": 0,
            "config": {
                "partition": partition,
                "hospital_id": hospital,
                "seed": seed,
                "days": 365,
                "mechanism_family": "v041",
                "dynamics": {
                    "arrivals": "v041", "discharges": "v041", "staffing": "v041",
                },
                "documentary": {
                    "staff_forecasts": "v041",
                    "downstream_confirmation": "v041",
                },
                "observation": {},
            },
        }

    return {
        "schema_version": "0.1",
        "plan": {"split_axis": "structure"},
        "worlds": [
            world("W_TRAIN_001", "H_TRAIN", "train", "a", 101),
            world("W_VALID_002", "H_VALID", "validation", "b", 102),
            world("W_PRIVATE_TEST_003", "H_PRIVATE_TEST", "test", "c", 103),
        ],
    }


def compile_fixture(
    registry: dict[str, Any] | None = None, *,
    temporal_dev_days: int = 28, embargo_hours: int = 24,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return compile_index(
        fixture() if registry is None else registry,
        model_spec=make_v041_synthetic_spec(),
        temporal_dev_days=temporal_dev_days,
        embargo_hours=embargo_hours,
    )


def test_compiles_three_exposure_partitions_not_test() -> None:
    index, summary = compile_fixture()
    assert index["schema"] == SCHEMA
    assert set(index["partitions"]) == {
        "train", "development_temporal", "development_ood"
    }
    assert summary["reserved_test_world_count"] == 1
    assert summary["test_trajectories_read"] is False
    assert index["training_allowed"] is False
    assert index["simulation"] is False
    assert index["model_forward"] is False
    assert index["partitions"]["train"][0]["world_id"] == "W_TRAIN_001"
    assert index["partitions"]["development_temporal"][0]["world_id"] == "W_TRAIN_001"
    assert index["partitions"]["development_ood"][0]["world_id"] == "W_VALID_002"
    serialized = json.dumps(index, sort_keys=True)
    assert "W_PRIVATE_TEST_003" not in serialized
    assert "H_PRIVATE_TEST" not in serialized
    assert '"seed": 103' not in serialized


def test_temporal_footprints_are_strictly_separated_by_embargo() -> None:
    index, _ = compile_fixture()
    train = index["partitions"]["train"][0]["origin_hours"]
    dev = index["partitions"]["development_temporal"][0]["origin_hours"]
    history = index["policy"]["history_steps"]
    horizon = index["policy"]["max_horizon_hours"]
    gap = index["policy"]["embargo_hours"]
    latest_train_target = train["last_origin_h"] + horizon
    first_dev_context = dev["first_origin_h"] - history + 1
    assert first_dev_context > latest_train_target + gap
    assert train["first_origin_h"] >= history
    assert dev["last_origin_h"] <= 365 * 24 - horizon


@pytest.mark.parametrize("corruption", [
    "repeat_hospital", "repeat_seed", "repeat_world", "repeat_axis",
    "missing_reserved", "unknown_split",
])
def test_split_identity_and_axis_leaks_fail_closed(corruption: str) -> None:
    original = fixture()
    worlds = original["worlds"]
    if corruption == "repeat_hospital":
        worlds[1]["config"]["hospital_id"] = "H_TRAIN"
    elif corruption == "repeat_seed":
        worlds[1]["config"]["seed"] = 101
    elif corruption == "repeat_world":
        worlds[1]["world_id"] = "W_TRAIN_001"
    elif corruption == "repeat_axis":
        worlds[1]["structure_sha256"] = "a" * 64
    elif corruption == "missing_reserved":
        worlds.pop()
    else:
        worlds[2]["config"]["partition"] = "development"
    with pytest.raises(ValueError):
        compile_fixture(original)


def test_ood_mechanism_axis_requires_distinct_family() -> None:
    original = fixture()
    original["plan"]["split_axis"] = "mechanism"
    with pytest.raises(ValueError, match="axis"):
        compile_fixture(original)
    original["worlds"][1]["config"]["mechanism_family"] = "local_v1"
    original["worlds"][2]["config"]["mechanism_family"] = "hybrid_v1"
    index, _ = compile_fixture(original)
    assert index["partitions"]["development_ood"][0]["heldout_axis_value"] == "local_v1"


def test_refuse_empty_and_unembargoed_temporal_ranges() -> None:
    raw = fixture()
    raw["worlds"][0]["config"]["days"] = 7
    with pytest.raises(ValueError, match="origin range"):
        compile_fixture(raw)
    with pytest.raises(ValueError, match="Invalid frozen"):
        compile_fixture(temporal_dev_days=0)
    with pytest.raises(ValueError, match="Invalid frozen"):
        compile_fixture(embargo_hours=-1)


def output_fixture(root: Path, *, index: dict[str, Any] | None = None) -> None:
    root.mkdir()
    if index is None:
        index, summary = compile_fixture()
    else:
        _, summary = compile_fixture()
    file = root / "index.json"
    file.write_text(json.dumps(index, sort_keys=True), encoding="utf-8")
    manifest = {
        "schema": SCHEMA,
        "status": "EXPOSURE_METADATA_ONLY_NO_TRAINING",
        "synthetic_only": True,
        "upstream_registry_sha256": "d" * 64,
        "upstream_manifest_sha256": "e" * 64,
        "model_spec_sha256": index["model_spec_sha256"],
        "index_sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
        "summary": summary,
        "holdout_status": "TEST_TRAJECTORIES_UNOPENED",
        "model_forward": False,
        "training": False,
        "simulation": False,
    }
    (root / "manifest.json").write_text(json.dumps(manifest))


def test_lower_privilege_inspector_needs_only_redacted_index(tmp_path: Path) -> None:
    output_fixture(tmp_path / "exposure")
    root = tmp_path / "exposure"
    expected_sha = hashlib.sha256((root / "index.json").read_bytes()).hexdigest()
    receipt = inspect(root, expected_index_sha256=expected_sha)
    assert receipt["status"] == "S0C_METADATA_HASH_VERIFIED_NO_HOLDOUT_ACCESS"
    assert receipt["training"] is False
    assert receipt["summary"]["reserved_test_world_count"] == 1


def test_inspector_rejects_tamper_and_reserved_partition_even_with_new_hash(
    tmp_path: Path,
) -> None:
    root = tmp_path / "exposure"
    output_fixture(root)
    source = json.loads((root / "index.json").read_text())
    changed = copy.deepcopy(source)
    changed["partitions"]["test"] = [{"world_id": "LEAK"}]
    (root / "index.json").write_text(json.dumps(changed))
    expected_sha = hashlib.sha256((root / "index.json").read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        inspect(root, expected_index_sha256=expected_sha)
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["index_sha256"] = hashlib.sha256((root / "index.json").read_bytes()).hexdigest()
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="test or unknown partition"):
        inspect(root, expected_index_sha256=expected_sha)



def test_external_operator_pin_is_mandatory_and_rejects_rewritten_manifest(
    tmp_path: Path,
) -> None:
    root = tmp_path / "exposure"
    output_fixture(root)
    with pytest.raises(PermissionError, match="externally pinned"):
        inspect(root, expected_index_sha256="")
    with pytest.raises(ValueError, match="Corrupt"):
        inspect(root, expected_index_sha256="f" * 64)


def test_semantic_overlap_is_rejected_even_with_a_matching_new_pin(
    tmp_path: Path,
) -> None:
    root = tmp_path / "exposure"
    output_fixture(root)
    index = json.loads((root / "index.json").read_text())
    temporal = index["partitions"]["development_temporal"][0]
    train = index["partitions"]["train"][0]
    temporal["origin_hours"]["first_origin_h"] = (
        train["origin_hours"]["last_origin_h"] + 1
    )
    raw = json.dumps(index, sort_keys=True)
    (root / "index.json").write_text(raw)
    sha = hashlib.sha256(raw.encode()).hexdigest()
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["index_sha256"] = sha
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="overlaps"):
        inspect(root, expected_index_sha256=sha)
