"""M3D.1 power-plan tests, including mandatory RNG reachability."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from hfwm.m3d.power import (
    SimulationDesign,
    audit_rng_reachability,
    design_grid,
    guardrail_decision,
    interval_procedure_status,
    retrospective_guardrail_decision,
    run_power_plan,
    simulation_draws,
)


@pytest.fixture(scope="module")
def power_plan() -> dict[str, Any]:
    return run_power_plan(seed=20260829)


def test_power_simulation_rng_reachability_consumes_final_generator() -> None:
    first = simulation_draws(101, size=64)
    repeat = simulation_draws(101, size=64)
    different = simulation_draws(102, size=64)
    audit = audit_rng_reachability(101, size=64)
    assert np.array_equal(first, repeat)
    assert not np.array_equal(first, different)
    assert audit.same_seed_identical is True
    assert audit.different_seed_different is True
    assert audit.rng_state_consumed is True
    assert audit.seed_reaches_final_generator is True
    assert audit.first_output_hash == audit.repeat_output_hash
    assert audit.first_output_hash != audit.different_output_hash
    assert audit.initial_state_hash != audit.final_state_hash


def test_three_way_guardrail_and_inconclusive_decision() -> None:
    assert guardrail_decision(0.00, 0.01) == "PASS_GUARDRAIL"
    assert guardrail_decision(0.10, 0.01) == "FAIL_GUARDRAIL"
    assert guardrail_decision(0.05, 0.02) == "INCONCLUSIVE_GUARDRAIL"
    assert interval_procedure_status(0.049, 0.050) == "BOUNDARY_CALIBRATION_PASS"
    assert interval_procedure_status(0.049, 0.051) == "BOUNDARY_CALIBRATION_NOT_DEMONSTRATED"
    assert interval_procedure_status(0.051, 0.060) == "INTERVAL_PROCEDURE_UNDERCOVERS"
    assert interval_procedure_status(0.049) == "BOUNDARY_CALIBRATION_NOT_DEMONSTRATED"


def test_frozen_grid_has_required_internal_episode_counts() -> None:
    designs = design_grid()
    assert [design.episode_count for design in designs] == [
        192,
        224,
        256,
        288,
        320,
        352,
        384,
        512,
        640,
        768,
    ]
    assert all(design.hospital_group_count == 1 for design in designs)
    assert all(
        design.window_overlap_policy == "NON_OVERLAPPING_EPISODES_ONLY" for design in designs
    )


def test_full_plan_includes_delta_zero_and_separates_count_rate(
    power_plan: dict[str, Any],
) -> None:
    scenarios = power_plan["scenarios"]
    assert {scenario["endpoint_semantics"] for scenario in scenarios} == {"COUNT", "RATE"}
    assert {scenario["episode_count"] for scenario in scenarios} == {
        192,
        224,
        256,
        288,
        320,
        352,
        384,
        512,
        640,
        768,
    }
    for scenario in scenarios:
        assert set(scenario["guardrail"]) == {
            "true_delta_00pct",
            "true_delta_05pct",
            "true_delta_10pct",
            "true_delta_15pct",
        }
        for cell in scenario["guardrail"].values():
            assert cell["valid_simulations"] >= 40_000
            assert cell["non_finite_simulations"] == 0
            assert cell["delta_occ_relative"] == cell["true_delta_occ"]
            assert cell["delta_occ_absolute"] == pytest.approx(
                cell["error_candidate_absolute"] - cell["error_local_absolute"]
            )


def test_two_speed_monte_carlo_precision_and_non_undercoverage(
    power_plan: dict[str, Any],
) -> None:
    assert power_plan["ordinary_precision_ok"] is True
    assert power_plan["critical_precision_ok"] is True
    assert power_plan["interval_procedure_valid_at_boundary"] is True
    assert power_plan["boundary_calibration_status"] == {
        "COUNT": "BOUNDARY_CALIBRATION_PASS",
        "RATE": "BOUNDARY_CALIBRATION_PASS",
    }
    selected = power_plan["selected_design_id"]
    assert isinstance(selected, str)
    selected_rows = [row for row in power_plan["scenarios"] if row["design_id"] == selected]
    assert len(selected_rows) == 2
    for row in selected_rows:
        boundary = row["guardrail"]["true_delta_05pct"]
        assert boundary["valid_simulations"] >= 80_000
        assert boundary["fail_guardrail"]["mc_ci95_lower"] <= 0.05
        assert boundary["fail_guardrail"]["mc_ci95_half_width"] <= 0.0015


def test_joint_selection_rule_and_m2c_184_never_unlocks(
    power_plan: dict[str, Any],
) -> None:
    selected = power_plan["selected_design_id"]
    assert power_plan["selection_status"] == "ACCEPTABLE_DESIGN_SELECTED"
    assert isinstance(selected, str)
    scenarios = power_plan["scenarios"]
    selected_rows = [row for row in scenarios if row["design_id"] == selected]
    assert len(selected_rows) == 2
    for row in selected_rows:
        zero = row["guardrail"]["true_delta_00pct"]
        boundary = row["guardrail"]["true_delta_05pct"]
        assert row["primary_power"]["probability"] >= 0.80
        assert zero["fail_guardrail"]["probability"] <= 0.01
        assert zero["inconclusive_guardrail"]["probability"] <= 0.20
        assert boundary["fail_guardrail"]["mc_ci95_lower"] <= 0.05
        assert row["guardrail"]["true_delta_10pct"]["fail_guardrail"]["probability"] >= 0.80
        assert row["guardrail"]["true_delta_15pct"]["fail_guardrail"]["probability"] >= 0.95
    assert power_plan["historical_m2c_estimate"] == 184
    assert power_plan["historical_estimate_is_unlock_gate"] is False
    assert power_plan["previous_planning_point"] == 384
    assert power_plan["training_authorized"] is False


def test_pessimistic_icc_sensitivity_is_reported(power_plan: dict[str, Any]) -> None:
    assumptions = power_plan["icc_assumptions"]
    assert assumptions["baseline_status"] == "POSTULATED_NOT_PARTNER_ESTIMATE"
    assert assumptions["m2_values_are_not_partner_estimates"] is True
    assert assumptions["pessimistic_site_icc"] > assumptions["baseline_site_icc"]
    sensitivity = power_plan["icc_sensitivity"]
    assert sensitivity["selection_status"] == "ACCEPTABLE_DESIGN_SELECTED"
    assert sensitivity["final_internal_episode_requirement"] >= power_plan[
        "final_internal_episode_requirement"
    ]


def test_m2_point_estimate_is_inconclusive_under_new_three_way_rule() -> None:
    result = retrospective_guardrail_decision(
        0.17307578440112872,
        0.1031056874381268,
        observed_design_effect=2.22192,
    )
    assert result["decision"] == "INCONCLUSIVE_GUARDRAIL"
    assert result["lower_one_sided_95"] < 0.05


def test_power_artifact_persists_m2_retrospective_result(
    power_plan: dict[str, Any],
) -> None:
    result = power_plan["m2_retrospective"]
    assert result["decision"] == "INCONCLUSIVE_GUARDRAIL"
    assert result["point_regression"] == pytest.approx(0.17307578440112872)


def test_inconclusive_has_no_promotion_kill_or_same_protocol_extension(
    power_plan: dict[str, Any],
) -> None:
    assert power_plan["inconclusive_real_experiment_decision"] == {
        "candidate_promotion": "forbidden",
        "noninferiority_claim": "forbidden",
        "scientific_kill_claim": "forbidden",
        "deployment_oriented_evaluation": "forbidden",
        "guardrail_satisfaction_claim": "forbidden",
        "governance_action": "HOLD_NO_ADVANCE",
        "result_status": "M3_RESULT_INCONCLUSIVE",
        "evaluation_status": "CLOSED_AND_FROZEN",
        "post_result_rescue_in_same_evaluation": "forbidden",
        "resolution": "NEW_INDEPENDENT_EVALUATION_WITH_UNUSED_DATA_REQUIRED",
        "blinded_sample_size_insufficient_status": (
            "NO_GO_M3_INSUFFICIENT_EFFECTIVE_SAMPLE_SIZE"
        ),
        "same_protocol_post_result_extension": "forbidden",
    }


def test_invalid_small_monte_carlo_budgets_are_rejected() -> None:
    with pytest.raises(ValueError, match="ordinary grid"):
        run_power_plan(ordinary_repetitions=39_999)
    design = SimulationDesign("valid", 1, 6, 2, 8, 2)
    assert design.episode_count == 192
