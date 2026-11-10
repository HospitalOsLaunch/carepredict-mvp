"""Offline S0c metadata and blind holdout guard tests. No data opened."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from research_lab.s0c_world_registry import (
    SCHEMA,
    build_registry,
    validate_job_scope,
)


def fixture() -> list[dict[str, Any]]:
    rows = []
    for i, partition in enumerate(
        ("train", "train", "development", "validation", "ood_blind")
    ):
        rows.append({
            "world_id": f"world-{i}",
            "partition": partition,
            "hospital_id": f"H{i}",
            "generator_family": ("v041", "local_v1", "hybrid_v1")[i % 3],
            "observation_profile": "v041",
            "policy_family": "reference_policy",
            "structure_family": "blind_structure" if i == 4 else "known_structure",
            "seed_group": f"generator-lineage-{i}",
            "source_manifest_sha256": f"{i + 1:064x}",
            "observation_manifest_sha256": f"{i + 10:064x}",
            "action_manifest_sha256": f"{i + 20:064x}",
            "source_clock": "fixed_utc_plus_01_no_dst",
            "mechanism_tags": ["resource_queues", "policy_actions"],
            "readable_by_lab": partition != "ood_blind",
        })
    return rows


def registry() -> dict[str, Any]:
    return build_registry(fixture(), freeze_id="cycle-01-s0c-v1")


def test_sealed_registry_has_no_blind_details() -> None:
    result = registry()
    assert result["schema"] == SCHEMA
    assert result["split_counts"] == {
        "train": 2, "development": 1, "validation": 1, "ood_blind": 1
    }
    assert result["blind_world_count"] == 1
    assert result["training_enabled"] is False
    assert result["reserved_holdout_opened"] is False
    assert all(w["partition"] != "ood_blind" for w in result["readable_worlds"])
    assert "blind_structure" not in str(result)
    assert "world-4" not in str(result)


def test_allowed_training_and_dev_scope_do_not_grant_training() -> None:
    result = registry()
    train = validate_job_scope(result, ["world-0", "world-1"], "train")
    assert train["training_authorized"] is False
    assert train["status"] == "SCOPE_VALIDATED_NO_EXECUTION"
    dev = validate_job_scope(result, ["world-2"], "development_evaluation")
    assert dev["training_authorized"] is False


@pytest.mark.parametrize(
    ("purpose", "worlds"),
    [
        ("train", ["world-2"]),
        ("train", ["world-3"]),
        ("train", ["world-4"]),
        ("development_evaluation", ["world-3"]),
        ("development_evaluation", ["world-4"]),
        ("validation_once", ["world-3"]),
        ("train", ["world-0", "world-0"]),
    ],
)
def test_scope_refuses_leakage(purpose: str, worlds: list[str]) -> None:
    with pytest.raises((PermissionError, ValueError)):
        validate_job_scope(registry(), worlds, purpose)


def test_seed_lineage_cannot_cross_splits() -> None:
    rows = fixture()
    rows[2]["seed_group"] = rows[0]["seed_group"]
    with pytest.raises(ValueError, match="Seed lineage"):
        build_registry(rows, freeze_id="cycle-01-s0c-v1")


def test_repeated_source_or_action_archive_rejected() -> None:
    rows = fixture()
    rows[2]["source_manifest_sha256"] = rows[0]["source_manifest_sha256"]
    with pytest.raises(ValueError, match="Same source"):
        build_registry(rows, freeze_id="cycle-01-s0c-v1")
    rows = fixture()
    rows[2]["action_manifest_sha256"] = rows[0]["action_manifest_sha256"]
    with pytest.raises(ValueError, match="Action archive"):
        build_registry(rows, freeze_id="cycle-01-s0c-v1")


def test_blind_world_must_have_new_structure_and_no_read_access() -> None:
    rows = fixture()
    rows[-1]["structure_family"] = "known_structure"
    with pytest.raises(ValueError, match="hold out"):
        build_registry(rows, freeze_id="cycle-01-s0c-v1")
    rows = fixture()
    rows[-1]["readable_by_lab"] = True
    with pytest.raises(PermissionError, match="Blind"):
        build_registry(rows, freeze_id="cycle-01-s0c-v1")


def test_blind_commitment_changes_without_exposing_contents() -> None:
    first = registry()
    rows = deepcopy(fixture())
    rows[-1]["seed_group"] = "generator-lineage-revised"
    second = build_registry(rows, freeze_id="cycle-01-s0c-v1")
    assert first["blind_metadata_commitment_sha256"] != (
        second["blind_metadata_commitment_sha256"]
    )
    assert "generator-lineage-revised" not in str(second)


def test_unrecognized_source_clock_and_bad_hash_refused() -> None:
    rows = fixture()
    rows[0]["source_clock"] = "Europe/Paris"
    with pytest.raises(ValueError, match="clock"):
        build_registry(rows, freeze_id="cycle-01-s0c-v1")
    rows = fixture()
    rows[0]["source_manifest_sha256"] = "not-a-hash"
    with pytest.raises(ValueError, match="sha256"):
        build_registry(rows, freeze_id="cycle-01-s0c-v1")
