"""Contract tests for M3D synthetic fixtures and pre-data specifications."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from hfwm.m3d.contracts import (
    assert_fixture_only,
    configuration_hash,
    generate_assumed_questions,
    independent_cluster_key,
    occupancy_rate,
    prediction_hash,
    replayability_decision,
    score_replayability,
    simulation_output_hash,
    stock_flow_next,
    validate_transfer_coupling,
    weights_hash,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = ROOT / "tests/fixtures/hfwm/m3d_synthetic_contract.yaml"
DATA_CONTRACT_PATH = ROOT / "docs/research/hfwm/HFWM_R0_M3_DATA_CONTRACT.yaml"
EPISODE_SPEC_PATH = ROOT / "docs/research/hfwm/HFWM_R0_M3_EPISODE_SPEC.yaml"
REPLAY_SPEC_PATH = ROOT / "docs/research/hfwm/HFWM_R0_M3_REPLAYABILITY_SPEC.yaml"
CURRENT_MILESTONE_PATH = ROOT / "docs/research/hfwm/CURRENT_MILESTONE.yaml"
M3_DRAFT_PATH = ROOT / "docs/research/hfwm/HFWM_R0_M3_DRAFT.yaml"
HOLDOUT_POLICY_PATH = ROOT / "docs/research/hfwm/HFWM_R0_M3F_HOLDOUT_POLICY.yaml"
M2_RESULTS_PATH = ROOT / "artifacts/hfwm-r0/bakeoff-m2b/results.json"

EXPECTED_M2_RESULT = {
    "candidate_status": "REJECTED_BY_OCCUPANCY_GUARDRAIL",
    "procedural_basis": "PRE_REGISTERED_POINT_ESTIMATE_RULE",
    "primary_superiority": "INCONCLUSIVE",
    "primary_inferiority": "NOT_DEMONSTRATED",
    "occupation_guardrail": "FAILED_PROCEDURALLY",
    "true_occupation_regression": "NOT_ESTIMATED_WITH_DECISION_GRADE_PRECISION",
    "world_model_advantage": "NOT_TESTABLE_ON_M1",
}

EXPECTED_M2_PREREGISTRATION_STATUS = {
    "m2_preregistration_contract_conformance": "SUPPORTED",
    "m2_execution_time_validator_state": "UNRESOLVED",
    "m2_software_gate_enforcement_at_execution": "NOT_PROVEN",
    "m2_overall_preregistration_assurance": "PARTIAL",
    "m2_code_state_not_fully_recoverable": True,
}


def load_yaml(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


@pytest.fixture
def fixture_document() -> dict[str, Any]:
    return load_yaml(FIXTURE_PATH)


def test_stock_flow_identity_and_event_categories(fixture_document: dict[str, Any]) -> None:
    interval = fixture_document["closed_interval"]
    result = stock_flow_next(
        interval["census_start"],
        external_entries=interval["external_entries"],
        internal_inbound_transfers=interval["internal_inbound_transfers"],
        external_exits=interval["external_exits"],
        internal_outbound_transfers=interval["internal_outbound_transfers"],
        other_signed_census_adjustments=interval["other_signed_census_adjustments"],
    )
    assert result == interval["census_end"] == 12
    assert {"birth_when_entering_census", "leave_permission", "return_from_permission"} <= set(
        interval["event_examples"]
    )


def test_count_rate_distinction_when_open_beds_change(
    fixture_document: dict[str, Any],
) -> None:
    t0 = fixture_document["count_rate_divergence"]["t0"]
    t1 = fixture_document["count_rate_divergence"]["t1"]
    assert t0["patient_census_count"] == t1["patient_census_count"]
    assert occupancy_rate(t0["patient_census_count"], t0["open_bed_count"]) == pytest.approx(
        t0["occupancy_rate"]
    )
    assert occupancy_rate(t1["patient_census_count"], t1["open_bed_count"]) == pytest.approx(
        t1["occupancy_rate"]
    )
    assert t0["occupancy_rate"] != t1["occupancy_rate"]
    with pytest.raises(TypeError):
        stock_flow_next(
            10.0,
            external_entries=0,
            internal_inbound_transfers=0,
            external_exits=0,
            internal_outbound_transfers=0,
            other_signed_census_adjustments=0,
        )  # type: ignore[arg-type]


def test_transfer_a_to_b_coupling_and_broken_pair(fixture_document: dict[str, Any]) -> None:
    assert validate_transfer_coupling(fixture_document["transfer_events"]) == []
    assert validate_transfer_coupling(fixture_document["broken_transfer_events"]) == [
        "transfer-broken-001"
    ]


def test_transfer_fallback_pairs_one_to_one_and_rejects_incompatible_source_records() -> None:
    def leg(kind: str, source_record_id: str, destination: str) -> dict[str, Any]:
        return {
            "event_type": kind,
            "source_record_id": source_record_id,
            "source_unit_id": "unit-a",
            "destination_unit_id": destination,
            "event_time": "2026-01-01T02:00:00Z",
        }

    two_valid_pairs = [
        leg("internal_outbound_transfer", "row-1", "unit-b"),
        leg("internal_inbound_transfer", "row-1", "unit-b"),
        leg("internal_outbound_transfer", "row-2", "unit-c"),
        leg("internal_inbound_transfer", "row-2", "unit-c"),
    ]
    assert validate_transfer_coupling(two_valid_pairs) == []
    incompatible = [
        leg("internal_outbound_transfer", "row-out", "unit-b"),
        leg("internal_inbound_transfer", "row-in", "unit-b"),
    ]
    broken = validate_transfer_coupling(incompatible)
    assert len(broken) == 2
    assert all(item.startswith("fallback:") for item in broken)


def test_units_within_site_are_not_independent() -> None:
    unit_a = {
        "hospital_group_id": "g",
        "hospital_site_id": "s",
        "unit_id": "a",
        "temporal_block_id": "b",
    }
    unit_b = {**unit_a, "unit_id": "b"}
    assert independent_cluster_key(unit_a) == independent_cluster_key(unit_b) == ("g", "s", "b")
    other_group = {**unit_a, "hospital_group_id": "g2"}
    assert independent_cluster_key(other_group) != independent_cluster_key(unit_a)


def test_hash_domains_are_pure() -> None:
    learned = {"coefficient": [1.0, 2.0], "bias": [0.25]}
    predictions = [[1.25, 2.25], [1.5, 2.5]]
    config_a = {"ridge": 1.0, "seed": 1729}
    config_b = {"ridge": 1.0, "seed": 2718}
    assert weights_hash(learned) == weights_hash(learned)
    assert configuration_hash(config_a) != configuration_hash(config_b)
    assert prediction_hash(predictions) == prediction_hash(predictions)
    assert weights_hash(learned) != configuration_hash(config_a)
    simulation_a = {"draws": [0.1, 0.2], "seed": 1729}
    hash_a = simulation_output_hash(simulation_a)
    assert simulation_output_hash({**simulation_a, "simulation_output_hash": hash_a}) == hash_a
    assert simulation_output_hash({"draws": [0.1, 0.3], "seed": 1729}) != hash_a


def test_m2_four_configurations_are_deterministic_not_independent_seeds() -> None:
    results = json.loads(M2_RESULTS_PATH.read_text(encoding="utf-8"))
    by_arm: dict[str, list[dict[str, Any]]] = {}
    for run in results["raw_runs"]:
        by_arm.setdefault(run["arm_id"], []).append(run)
    assert set(by_arm) == {
        "mechanistic_queue_semimarkov",
        "local_joint_from_scratch",
        "shared_hfwm_multitask",
        "hgbr_cqr",
    }
    for runs in by_arm.values():
        assert {run["seed"] for run in runs} == {1729, 2718, 3141}
        assert len({run["prediction_hash"] for run in runs}) == 1
        assert len({json.dumps(run["raw_test"]["free_running_predictions"]) for run in runs}) == 1


def test_all_assumed_conventions_generate_partner_questions() -> None:
    documents = [load_yaml(DATA_CONTRACT_PATH), load_yaml(EPISODE_SPEC_PATH)]
    questions = generate_assumed_questions(*documents)
    assumed_count = sum(
        1
        for document in documents
        for value in _walk_values(document)
        if isinstance(value, dict) and value.get("status") == "assumed"
    )
    assert len(questions) == assumed_count
    assert len({question["convention_path"] for question in questions}) == assumed_count


def test_m2_epistemic_result_is_exact_and_m3_stays_unauthorized() -> None:
    data_contract = load_yaml(DATA_CONTRACT_PATH)
    current = load_yaml(CURRENT_MILESTONE_PATH)
    draft = load_yaml(M3_DRAFT_PATH)
    assert {
        key: data_contract["m2_result"][key] for key in EXPECTED_M2_RESULT
    } == EXPECTED_M2_RESULT
    assert {
        key: current["m2_result"][key] for key in EXPECTED_M2_RESULT
    } == EXPECTED_M2_RESULT
    assert {
        key: current["m2_result"][key]
        for key in EXPECTED_M2_PREREGISTRATION_STATUS
    } == EXPECTED_M2_PREREGISTRATION_STATUS
    assert draft["m2_result"] == EXPECTED_M2_RESULT
    assert data_contract["training_authorized"] is False
    assert draft["m3l_authorized"] is False
    assert draft["m3f_authorized"] is False


def test_hcl_nantes_dijon_separation_is_frozen() -> None:
    policy = load_yaml(HOLDOUT_POLICY_PATH)
    assert policy["hcl"]["organization_count_for_inference"] == 1
    assert policy["hcl"]["independent_institutions_claim"] == "forbidden"
    assert policy["nantes"]["role"] == "FUTURE_M3F_HOLDOUT_ONLY"
    assert policy["nantes"]["data_requested_for_m3l"] is False
    assert policy["dijon"]["dijon_strategy"] == "UNDECIDED"
    assert policy["m3l_authorized"] is False
    assert policy["m3f_authorized"] is False


def _walk_values(value: Any) -> list[Any]:
    values = [value]
    if isinstance(value, dict):
        for child in value.values():
            values.extend(_walk_values(child))
    elif isinstance(value, list):
        for child in value:
            values.extend(_walk_values(child))
    return values


def test_partial_replayability_and_frozen_eligibility_mask(
    fixture_document: dict[str, Any],
) -> None:
    spec = load_yaml(REPLAY_SPEC_PATH)
    thresholds = spec["dimensions"]
    partial = fixture_document["replayability_vectors"]["partial_replayability"]
    partial_scores = score_replayability(partial["evidence"], rubric=thresholds)
    partial_decision = replayability_decision(
        partial_scores,
        thresholds=thresholds,
        historical_available_at=partial["historical_available_at"],
    )
    assert partial_decision.eligible is True
    assert partial_decision.historical_realtime_claim_allowed is False
    assert "historical_available_at_missing_retro_only" in partial_decision.exclusion_reasons

    outage = fixture_document["replayability_vectors"]["source_outage"]
    outage_scores = score_replayability(outage["evidence"], rubric=thresholds)
    outage_decision = replayability_decision(
        outage_scores,
        thresholds=thresholds,
        historical_available_at=outage["historical_available_at"],
    )
    assert outage_decision.eligible is False
    assert "semantic_completeness" in outage_decision.hard_fail_dimensions
    assert fixture_document["eligibility_mask"]["frozen_before_outcomes"] is True


def test_replayability_scores_are_reconstructed_and_missing_evidence_fails(
    fixture_document: dict[str, Any],
) -> None:
    spec = load_yaml(REPLAY_SPEC_PATH)
    thresholds = spec["dimensions"]
    complete = fixture_document["replayability_vectors"]["complete_unit_block"]
    complete_scores = score_replayability(complete["evidence"], rubric=thresholds)
    assert set(complete_scores.values()) == {100.0}
    incomplete_evidence = {
        **complete["evidence"],
        "semantic_completeness": {"census_definition_confirmed": True},
    }
    incomplete_scores = score_replayability(incomplete_evidence, rubric=thresholds)
    assert incomplete_scores["semantic_completeness"] == 30.0
    decision = replayability_decision(
        incomplete_scores, thresholds=thresholds, historical_available_at=True
    )
    assert decision.eligible is False
    assert "semantic_completeness" in decision.hard_fail_dimensions


def test_fixtures_cannot_claim_data_in_hand(fixture_document: dict[str, Any]) -> None:
    assert_fixture_only(fixture_document)
    forged = {**fixture_document, "data_status": "DATA_IN_HAND"}
    with pytest.raises(ValueError, match="data-in-hand"):
        assert_fixture_only(forged)


def test_temporal_fallback_and_special_cases_are_explicit(
    fixture_document: dict[str, Any],
) -> None:
    assert fixture_document["future_correction"]["visible_at_analysis_as_of"] is False
    assert fixture_document["missing_available_at"]["available_at"] is None
    assert fixture_document["small_cell"]["release_policy"] == "PARTNER_DEFINED_CONTROL_REQUIRED"
    conventions = fixture_document["operating_room_conventions"]
    assert conventions["source_census_retained"]["departure_changes_census"] is False
    assert conventions["source_census_exited"]["departure_changes_census"] is True
