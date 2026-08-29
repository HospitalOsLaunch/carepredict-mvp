"""Tests for executable pre-training preregistration validation."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

from hfwm.evaluation.preregistration import validate_preregistration

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PREREGISTRATION = REPOSITORY_ROOT / "docs" / "research" / "hfwm"


def test_repository_preregistration_is_valid_before_training() -> None:
    """The checked-in contracts are mutually consistent and content-addressed."""
    result = validate_preregistration(PREREGISTRATION)
    assert result.valid, result.errors
    assert result.main_runs_authorized is True
    assert result.errors == ()
    assert len(result.manifest["entries"]) == 11
    assert len(result.manifest["manifest_sha256"]) == 64


def test_bounded_m2a_contract_excludes_unverified_tsfm_and_has_no_results() -> None:
    """M2A is self-contained, bounded to M1 and frozen before comparative runs."""

    bakeoff = json.loads((PREREGISTRATION / "HFWM_R0_BAKEOFF.yaml").read_text())
    primary_ids = [item["id"] for item in bakeoff["candidate_families"]]
    final_ids = [item["id"] for item in bakeoff["final_gate_comparators"]]
    excluded_ids = [item["id"] for item in bakeoff["excluded_comparators"]]

    assert bakeoff["results_status"] == "NOT_EXECUTED"
    assert bakeoff["tasks"] == ["occupancy", "inflow"]
    assert bakeoff["horizons_hours"] == [6]
    assert bakeoff["rollout_steps"] == 4
    assert primary_ids == [
        "mechanistic_queue_semimarkov",
        "local_joint_from_scratch",
        "shared_hfwm_multitask",
    ]
    assert final_ids == ["hgbr_cqr"]
    assert excluded_ids == ["generic_tsfm"]


def test_validator_rejects_fourth_family_and_tsfm_without_not_executed(tmp_path: Path) -> None:
    """The bounded bake-off and offline TSFM gate are fail-closed."""
    target = tmp_path / "hfwm"
    shutil.copytree(PREREGISTRATION, target)
    bakeoff_path = target / "HFWM_R0_BAKEOFF.yaml"
    bakeoff = json.loads(bakeoff_path.read_text(encoding="utf-8"))
    bakeoff["candidate_families"].append(
        {"id": "fourth", "kind": "shared_hfwm", "hypothesis": "forbidden expansion"}
    )
    for comparator in bakeoff["final_gate_comparators"]:
        if comparator["id"] == "generic_tsfm":
            comparator["status"] = "READY"
    bakeoff_path.write_text(json.dumps(bakeoff), encoding="utf-8")
    result = validate_preregistration(target)
    assert not result.valid
    assert "bakeoff must define between one and three candidate_families" in result.errors


def test_validator_rejects_unequal_learned_compute_budget(tmp_path: Path) -> None:
    """Shared pretraining cannot receive an undeclared bake-off compute advantage."""
    target = tmp_path / "hfwm"
    shutil.copytree(PREREGISTRATION, target)
    bakeoff_path = target / "HFWM_R0_BAKEOFF.yaml"
    bakeoff = json.loads(bakeoff_path.read_text(encoding="utf-8"))
    bakeoff["candidate_families"][2]["accelerator_hours_max_per_seed"] = 2
    bakeoff_path.write_text(json.dumps(bakeoff), encoding="utf-8")
    result = validate_preregistration(target)
    assert not result.valid
    assert (
        "local and shared candidates must have equal accelerator_hours_max_per_seed"
        in result.errors
    )


def test_validator_rejects_incomplete_run_and_comparator_budget(tmp_path: Path) -> None:
    """Every arm and final comparator must freeze run, compute and capacity scope."""
    target = tmp_path / "hfwm"
    shutil.copytree(PREREGISTRATION, target)
    bakeoff_path = target / "HFWM_R0_BAKEOFF.yaml"
    bakeoff = json.loads(bakeoff_path.read_text(encoding="utf-8"))
    del bakeoff["candidate_families"][0]["runs_per_seed"]
    del bakeoff["final_gate_comparators"][0]["cpu_seconds_max_per_seed"]
    bakeoff_path.write_text(json.dumps(bakeoff), encoding="utf-8")

    result = validate_preregistration(target)

    assert not result.valid
    assert "mechanistic.runs_per_seed must be exactly one" in result.errors
    assert "HGBR/CQR must freeze non-negative compute budgets" in result.errors


def test_validator_rejects_spec_bakeoff_candidate_mismatch(tmp_path: Path) -> None:
    """The chartered candidates and executable bake-off cannot silently diverge."""
    target = tmp_path / "hfwm"
    shutil.copytree(PREREGISTRATION, target)
    spec_path = target / "HFWM_R0_SPEC.yaml"
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    spec["primary_families"]["candidates"][0]["candidate_id"] = "different"
    spec_path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    result = validate_preregistration(target)
    assert not result.valid
    assert "spec and bakeoff candidate ids differ" in result.errors
