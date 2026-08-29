"""Pre-data guardrail simulation for the frozen M3D.1 analysis plan.

The simulator works on planning sufficient statistics.  It never fits a model and
never reads partner data.  Sites and temporal blocks, rather than targets, rollout
steps, windows, or seed labels, determine the effective sample size.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from statistics import NormalDist
from typing import TypeAlias, cast

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True, slots=True)
class SimulationDesign:
    """A nested planning structure; episodes are not assumed independent."""

    design_id: str
    hospital_group_count: int
    hospital_site_count: int
    unit_count_per_site: int
    independent_temporal_block_count: int
    episodes_per_block: int
    site_icc: float = 0.15
    within_block_icc: float = 0.20
    window_overlap_policy: str = "NON_OVERLAPPING_EPISODES_ONLY"

    @property
    def episode_count(self) -> int:
        return (
            self.hospital_group_count
            * self.hospital_site_count
            * self.unit_count_per_site
            * self.independent_temporal_block_count
            * self.episodes_per_block
        )

    @property
    def design_effect(self) -> float:
        """Frozen planning inflation for nested units and same-block episodes."""
        return (
            1.0
            + self.site_icc * (self.unit_count_per_site - 1)
            + self.within_block_icc * (self.episodes_per_block - 1)
        )

    @property
    def degrees_of_freedom(self) -> int:
        # Inference cannot invent independence from units nested within sites.
        return max(
            2,
            min(self.hospital_site_count - 1, self.independent_temporal_block_count - 1),
        )


@dataclass(frozen=True, slots=True)
class RNGReachability:
    seed: int
    same_seed_identical: bool
    different_seed_different: bool
    rng_state_consumed: bool
    seed_reaches_final_generator: bool
    first_output_hash: str
    repeat_output_hash: str
    different_output_hash: str
    initial_state_hash: str
    final_state_hash: str


def _canonical_hash(value: JsonValue) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _array_hash(values: FloatArray) -> str:
    return hashlib.sha256(values.astype("<f8", copy=False).tobytes()).hexdigest()


def simulation_draws(seed: int, size: int = 32, *, degrees_of_freedom: int = 7) -> FloatArray:
    """Expose the exact final RNG entrypoint for mandatory reachability tests."""
    if size <= 0:
        raise ValueError("size must be positive")
    if degrees_of_freedom <= 1:
        raise ValueError("degrees_of_freedom must be greater than one")
    return np.random.default_rng(seed).standard_t(degrees_of_freedom, size=size).astype(np.float64)


def audit_rng_reachability(
    seed: int, *, size: int = 128, degrees_of_freedom: int = 7
) -> RNGReachability:
    """Prove that the declared seed reaches and is consumed by the final generator."""

    def traced(run_seed: int) -> tuple[FloatArray, str, str]:
        rng = np.random.default_rng(run_seed)
        before = _canonical_hash(cast(JsonValue, rng.bit_generator.state))
        output = rng.standard_t(degrees_of_freedom, size=size).astype(np.float64)
        after = _canonical_hash(cast(JsonValue, rng.bit_generator.state))
        return output, before, after

    first, before, after = traced(seed)
    repeat, repeat_before, repeat_after = traced(seed)
    different, _, _ = traced(seed + 1)
    same = bool(np.array_equal(first, repeat))
    distinct = bool(not np.array_equal(first, different))
    consumed = before != after and repeat_before != repeat_after
    return RNGReachability(
        seed=seed,
        same_seed_identical=same,
        different_seed_different=distinct,
        rng_state_consumed=consumed,
        seed_reaches_final_generator=same and distinct and consumed,
        first_output_hash=_array_hash(first),
        repeat_output_hash=_array_hash(repeat),
        different_output_hash=_array_hash(different),
        initial_state_hash=before,
        final_state_hash=after,
    )


def guardrail_decision(
    point_regression: float,
    standard_error: float,
    *,
    boundary: float = 0.05,
    critical_value: float | None = None,
) -> str:
    """Apply the frozen three-way occupation guardrail."""
    if standard_error < 0 or not math.isfinite(standard_error):
        raise ValueError("standard_error must be finite and non-negative")
    critical = critical_value or NormalDist().inv_cdf(0.95)
    if critical <= 0:
        raise ValueError("critical_value must be positive")
    upper = point_regression + critical * standard_error
    lower = point_regression - critical * standard_error
    if upper <= boundary:
        return "PASS_GUARDRAIL"
    if lower > boundary:
        return "FAIL_GUARDRAIL"
    return "INCONCLUSIVE_GUARDRAIL"


def interval_procedure_status(
    fail_probability_ci95_lower: float,
    fail_probability_ci95_upper: float | None = None,
) -> str:
    """Classify the Monte-Carlo boundary calibration using the UCB rule.

    The upper confidence bound is the only PASS criterion.  ``upper=None`` is
    retained solely as a compatibility path for historical callers; new release
    code must provide both bounds so an undemonstrated interval cannot pass.
    """
    if not 0.0 <= fail_probability_ci95_lower <= 1.0:
        raise ValueError("Monte-Carlo interval bound must be a probability")
    if fail_probability_ci95_upper is None:
        if fail_probability_ci95_lower > 0.05:
            return "INTERVAL_PROCEDURE_UNDERCOVERS"
        return "BOUNDARY_CALIBRATION_NOT_DEMONSTRATED"
    if not 0.0 <= fail_probability_ci95_upper <= 1.0:
        raise ValueError("Monte-Carlo interval bound must be a probability")
    if fail_probability_ci95_upper <= 0.05:
        return "BOUNDARY_CALIBRATION_PASS"
    if fail_probability_ci95_lower > 0.05:
        return "INTERVAL_PROCEDURE_UNDERCOVERS"
    return "BOUNDARY_CALIBRATION_NOT_DEMONSTRATED"


def retrospective_guardrail_decision(
    point_regression: float,
    iid_standard_error: float,
    *,
    observed_design_effect: float,
) -> dict[str, JsonValue]:
    """Apply the M3 three-way rule to a frozen historical point estimate.

    The nominal normal critical value is deliberately the most permissive plausible
    choice for declaring FAIL. Small-cluster calibration would only widen the interval.
    """
    if iid_standard_error <= 0 or observed_design_effect < 1:
        raise ValueError("positive standard error and design effect >= 1 are required")
    standard_error = iid_standard_error * math.sqrt(observed_design_effect)
    critical = NormalDist().inv_cdf(0.95)
    lower = point_regression - critical * standard_error
    upper = point_regression + critical * standard_error
    return {
        "point_regression": point_regression,
        "iid_standard_error": iid_standard_error,
        "observed_design_effect": observed_design_effect,
        "cluster_adjusted_standard_error": standard_error,
        "critical_value": critical,
        "lower_one_sided_95": lower,
        "upper_one_sided_95": upper,
        "decision": guardrail_decision(
            point_regression,
            standard_error,
            critical_value=critical,
        ),
    }


def _wilson_interval(successes: int, total: int, *, confidence: float = 0.95) -> dict[str, float]:
    if total <= 0 or not 0 <= successes <= total:
        raise ValueError("valid successes and total are required")
    z_value = NormalDist().inv_cdf(0.5 + confidence / 2.0)
    proportion = successes / total
    denominator = 1.0 + z_value**2 / total
    centre = (proportion + z_value**2 / (2.0 * total)) / denominator
    half = z_value * math.sqrt(
        proportion * (1.0 - proportion) / total + z_value**2 / (4.0 * total**2)
    ) / denominator
    return {
        "probability": proportion,
        "mc_ci95_lower": max(0.0, centre - half),
        "mc_ci95_upper": min(1.0, centre + half),
        "mc_ci95_half_width": half,
    }


def _endpoint_sigma(endpoint_semantics: str) -> float:
    if endpoint_semantics == "COUNT":
        return 0.25
    if endpoint_semantics == "RATE":
        return 0.29
    raise ValueError("endpoint_semantics must be COUNT or RATE")


def _standard_error(design: SimulationDesign, endpoint_semantics: str) -> float:
    effective_episode_count = design.episode_count / design.design_effect
    return _endpoint_sigma(endpoint_semantics) / math.sqrt(effective_episode_count)


def _calibrated_critical_value(
    design: SimulationDesign,
    *,
    seed: int,
    repetitions: int,
    calibration_tail_probability: float = 0.045,
) -> float:
    """Conservatively calibrate the one-sided interval before scenario runs."""
    if repetitions < 10_000:
        raise ValueError("at least 10000 calibration simulations are required")
    draws = simulation_draws(seed, repetitions, degrees_of_freedom=design.degrees_of_freedom)
    return float(np.quantile(draws, 1.0 - calibration_tail_probability, method="higher"))


def _cell(
    design: SimulationDesign,
    *,
    endpoint_semantics: str,
    true_delta_occ: float,
    seed: int,
    repetitions: int,
    critical_value: float,
) -> dict[str, JsonValue]:
    if repetitions < 1_000:
        raise ValueError("at least 1000 valid simulations are required")
    standard_error = _standard_error(design, endpoint_semantics)
    draws = simulation_draws(
        seed, repetitions, degrees_of_freedom=design.degrees_of_freedom
    )
    estimates = true_delta_occ + standard_error * draws
    finite = np.isfinite(estimates)
    valid_estimates = estimates[finite]
    valid_count = int(valid_estimates.size)
    non_finite_count = int(repetitions - valid_count)
    upper = valid_estimates + critical_value * standard_error
    lower = valid_estimates - critical_value * standard_error
    passes = int(np.count_nonzero(upper <= 0.05))
    failures = int(np.count_nonzero(lower > 0.05))
    inconclusive = valid_count - passes - failures
    control_error = 1.0
    candidate_error = control_error * (1.0 + true_delta_occ)
    return {
        "true_delta_occ": true_delta_occ,
        "error_local_absolute": control_error,
        "error_candidate_absolute": candidate_error,
        "delta_occ_absolute": candidate_error - control_error,
        "delta_occ_relative": true_delta_occ,
        "standard_error": standard_error,
        "valid_simulations": valid_count,
        "non_finite_simulations": non_finite_count,
        "pass_guardrail": cast(JsonValue, _wilson_interval(passes, valid_count)),
        "inconclusive_guardrail": cast(JsonValue, _wilson_interval(inconclusive, valid_count)),
        "fail_guardrail": cast(JsonValue, _wilson_interval(failures, valid_count)),
    }


def _primary_power(
    design: SimulationDesign,
    *,
    endpoint_semantics: str,
    seed: int,
    repetitions: int,
    critical_value: float,
) -> dict[str, JsonValue]:
    standard_error = _standard_error(design, endpoint_semantics)
    draws = simulation_draws(
        seed, repetitions, degrees_of_freedom=design.degrees_of_freedom
    )
    # The primary alternative is a 5% relative improvement (delta = -5%).
    estimates = -0.05 + standard_error * draws
    detections = int(np.count_nonzero(estimates + critical_value * standard_error < 0.0))
    return cast(dict[str, JsonValue], _wilson_interval(detections, repetitions))


def design_grid(
    *, site_icc: float = 0.15, within_block_icc: float = 0.20
) -> tuple[SimulationDesign, ...]:
    """Frozen grid; every product equals the displayed internal episode count."""
    return (
        SimulationDesign("episodes_192", 1, 6, 2, 8, 2, site_icc, within_block_icc),
        SimulationDesign("episodes_224", 1, 7, 2, 8, 2, site_icc, within_block_icc),
        SimulationDesign("episodes_256", 1, 8, 2, 8, 2, site_icc, within_block_icc),
        SimulationDesign("episodes_288", 1, 6, 3, 8, 2, site_icc, within_block_icc),
        SimulationDesign("episodes_320", 1, 8, 2, 10, 2, site_icc, within_block_icc),
        SimulationDesign("episodes_352", 1, 11, 2, 8, 2, site_icc, within_block_icc),
        SimulationDesign("episodes_384", 1, 8, 3, 8, 2, site_icc, within_block_icc),
        SimulationDesign("episodes_512", 1, 8, 4, 8, 2, site_icc, within_block_icc),
        SimulationDesign("episodes_640", 1, 10, 4, 8, 2, site_icc, within_block_icc),
        SimulationDesign("episodes_768", 1, 12, 4, 8, 2, site_icc, within_block_icc),
    )


def _simulate_design(
    design: SimulationDesign,
    *,
    endpoint_semantics: str,
    seed: int,
    repetitions: int,
    calibration_repetitions: int,
) -> dict[str, JsonValue]:
    critical = _calibrated_critical_value(
        design, seed=seed + 90_000, repetitions=calibration_repetitions
    )
    cells: dict[str, JsonValue] = {}
    for index, true_delta in enumerate((0.0, 0.05, 0.10, 0.15)):
        cells[f"true_delta_{int(true_delta * 100):02d}pct"] = _cell(
            design,
            endpoint_semantics=endpoint_semantics,
            true_delta_occ=true_delta,
            seed=seed + index,
            repetitions=repetitions,
            critical_value=critical,
        )
    return {
        **cast(dict[str, JsonValue], asdict(design)),
        "episode_count": design.episode_count,
        "design_effect": design.design_effect,
        "effective_episode_count": design.episode_count / design.design_effect,
        "degrees_of_freedom": design.degrees_of_freedom,
        "endpoint_semantics": endpoint_semantics,
        "critical_value": critical,
        "primary_power": _primary_power(
            design,
            endpoint_semantics=endpoint_semantics,
            seed=seed + 80_000,
            repetitions=repetitions,
            critical_value=critical,
        ),
        "guardrail": cells,
    }


def _probability(cell: dict[str, JsonValue], decision: str) -> float:
    value = cell[decision]
    if not isinstance(value, dict):
        raise TypeError(f"{decision} must be an interval mapping")
    probability = value["probability"]
    if not isinstance(probability, (float, int)):
        raise TypeError("probability must be numeric")
    return float(probability)


def _numeric(value: JsonValue, *, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"{name} must be numeric")
    return float(value)


def _eligible(result: dict[str, JsonValue]) -> bool:
    primary = result["primary_power"]
    guardrail = result["guardrail"]
    if not isinstance(primary, dict) or not isinstance(guardrail, dict):
        raise TypeError("malformed simulation result")
    zero = guardrail["true_delta_00pct"]
    boundary = guardrail["true_delta_05pct"]
    harm_10 = guardrail["true_delta_10pct"]
    harm_15 = guardrail["true_delta_15pct"]
    if not all(isinstance(value, dict) for value in (zero, boundary, harm_10, harm_15)):
        raise TypeError("malformed guardrail result")
    assert isinstance(zero, dict)
    assert isinstance(boundary, dict)
    assert isinstance(harm_10, dict)
    assert isinstance(harm_15, dict)
    fail_boundary = boundary["fail_guardrail"]
    if not isinstance(fail_boundary, dict):
        raise TypeError("malformed boundary interval")
    return bool(
        _numeric(primary["probability"], name="primary probability") >= 0.80
        and _probability(zero, "fail_guardrail") <= 0.01
        and _probability(zero, "inconclusive_guardrail") <= 0.20
        and _numeric(fail_boundary["mc_ci95_lower"], name="boundary lower") <= 0.05
        and _probability(harm_10, "fail_guardrail") >= 0.80
        and _probability(harm_15, "fail_guardrail") >= 0.95
    )


def _replace_boundary_with_critical_precision(
    result: dict[str, JsonValue],
    design: SimulationDesign,
    *,
    seed: int,
    critical_repetitions: int,
) -> None:
    endpoint = result["endpoint_semantics"]
    critical = result["critical_value"]
    guardrail = result["guardrail"]
    if not isinstance(endpoint, str) or not isinstance(critical, (int, float)):
        raise TypeError("malformed selected result")
    if not isinstance(guardrail, dict):
        raise TypeError("malformed selected guardrail")
    guardrail["true_delta_05pct"] = _cell(
        design,
        endpoint_semantics=endpoint,
        true_delta_occ=0.05,
        seed=seed,
        repetitions=critical_repetitions,
        critical_value=float(critical),
    )


def _select_and_refine(
    results: list[dict[str, JsonValue]],
    designs: tuple[SimulationDesign, ...],
    *,
    seed: int,
    critical_repetitions: int,
) -> SimulationDesign | None:
    selected: SimulationDesign | None = None
    for design in designs:
        matching = [item for item in results if item["design_id"] == design.design_id]
        if len(matching) == 2 and all(_eligible(item) for item in matching):
            selected = design
            break
    if selected is None:
        return None
    selected_results = [item for item in results if item["design_id"] == selected.design_id]
    for endpoint_index, item in enumerate(selected_results):
        _replace_boundary_with_critical_precision(
            item,
            selected,
            seed=seed + endpoint_index,
            critical_repetitions=critical_repetitions,
        )
    return selected if all(_eligible(item) for item in selected_results) else None


def run_power_plan(
    *,
    seed: int = 31_082_026,
    ordinary_repetitions: int = 40_000,
    critical_repetitions: int = 82_000,
    calibration_repetitions: int = 40_000,
) -> dict[str, JsonValue]:
    """Run the frozen planning grid without fitting a model or reading partner data."""
    if ordinary_repetitions < 40_000:
        raise ValueError("ordinary grid requires at least 40000 valid simulations per cell")
    if critical_repetitions < 80_000:
        raise ValueError("critical boundary requires at least 80000 valid simulations")
    reachability = audit_rng_reachability(seed)
    if not reachability.seed_reaches_final_generator:
        raise RuntimeError("simulation RNG reachability assertion failed")

    results: list[dict[str, JsonValue]] = []
    designs = design_grid()
    for endpoint_index, endpoint in enumerate(("COUNT", "RATE")):
        for design_index, design in enumerate(designs):
            results.append(
                _simulate_design(
                    design,
                    endpoint_semantics=endpoint,
                    seed=seed + endpoint_index * 100_000 + design_index * 1_000,
                    repetitions=ordinary_repetitions,
                    calibration_repetitions=calibration_repetitions,
                )
            )

    selected = _select_and_refine(
        results,
        designs,
        seed=seed + 900_000,
        critical_repetitions=critical_repetitions,
    )

    pessimistic_designs = design_grid(site_icc=0.30, within_block_icc=0.35)
    pessimistic_results: list[dict[str, JsonValue]] = []
    for endpoint_index, endpoint in enumerate(("COUNT", "RATE")):
        for design_index, design in enumerate(pessimistic_designs):
            pessimistic_results.append(
                _simulate_design(
                    design,
                    endpoint_semantics=endpoint,
                    seed=seed + 2_000_000 + endpoint_index * 100_000 + design_index * 1_000,
                    repetitions=ordinary_repetitions,
                    calibration_repetitions=calibration_repetitions,
                )
            )
    pessimistic_selected = _select_and_refine(
        pessimistic_results,
        pessimistic_designs,
        seed=seed + 2_900_000,
        critical_repetitions=critical_repetitions,
    )

    ordinary_precision_ok = True
    critical_precision_ok = selected is not None
    interval_procedure_valid = selected is not None
    boundary_calibration_statuses: dict[str, str] = {}
    for item in results:
        guardrail = item["guardrail"]
        if not isinstance(guardrail, dict):
            raise TypeError("malformed guardrail")
        for cell in guardrail.values():
            if not isinstance(cell, dict):
                raise TypeError("malformed cell")
            for decision in ("pass_guardrail", "inconclusive_guardrail", "fail_guardrail"):
                interval = cell[decision]
                if not isinstance(interval, dict):
                    raise TypeError("malformed Monte-Carlo interval")
                is_selected_boundary = bool(
                    selected is not None
                    and item["design_id"] == selected.design_id
                    and cell["true_delta_occ"] == 0.05
                )
                half_width = _numeric(interval["mc_ci95_half_width"], name="MC half width")
                if is_selected_boundary and decision == "fail_guardrail":
                    critical_precision_ok = critical_precision_ok and half_width <= 0.0015
                else:
                    ordinary_precision_ok = ordinary_precision_ok and half_width <= 0.005
        if selected is not None and item["design_id"] == selected.design_id:
            boundary = guardrail["true_delta_05pct"]
            if not isinstance(boundary, dict) or not isinstance(boundary["fail_guardrail"], dict):
                raise TypeError("malformed selected boundary")
            interval_procedure_valid = interval_procedure_valid and bool(
                interval_procedure_status(
                    _numeric(
                        boundary["fail_guardrail"]["mc_ci95_lower"],
                        name="boundary fail lower",
                    ),
                    _numeric(
                        boundary["fail_guardrail"]["mc_ci95_upper"],
                        name="boundary fail upper",
                    ),
                )
                == "BOUNDARY_CALIBRATION_PASS"
            )
            boundary_calibration_statuses[str(item["endpoint_semantics"])] = (
                interval_procedure_status(
                    _numeric(
                        boundary["fail_guardrail"]["mc_ci95_lower"],
                        name="boundary fail lower",
                    ),
                    _numeric(
                        boundary["fail_guardrail"]["mc_ci95_upper"],
                        name="boundary fail upper",
                    ),
                )
            )

    payload: dict[str, JsonValue] = {
        "schema_version": "hfwm.r0.m3d1.power-simulation.v2",
        "planning_only": True,
        "partner_data_consumed": False,
        "model_training_executed": False,
        "alpha_one_sided": 0.05,
        "target_power": 0.80,
        "target_relative_gain": 0.05,
        "min_harm_detection_power_delta_10pct": 0.80,
        "min_harm_detection_power_delta_15pct": 0.95,
        "relative_guardrail_margin": 0.05,
        "control_error_denominator": "error_local_absolute",
        "denominator_stability_check": "required",
        "max_false_kill_under_h0": 0.01,
        "max_inconclusive_rate_under_h0": 0.20,
        "ordinary_mc_half_width_limit": 0.005,
        "critical_boundary_mc_half_width_limit": 0.0015,
        "ordinary_repetitions": ordinary_repetitions,
        "critical_repetitions": critical_repetitions,
        "calibration_repetitions": calibration_repetitions,
        "historical_m2c_estimate": 184,
        "historical_estimate_is_unlock_gate": False,
        "previous_planning_point": 384,
        "final_internal_episode_requirement": (
            selected.episode_count if selected is not None else "NO_ACCEPTABLE_DESIGN_FOUND"
        ),
        "training_authorized": False,
        "rng_reachability": cast(JsonValue, asdict(reachability)),
        "selection_rule": (
            "SMALLEST_GRID_POINT_PASSING_PRIMARY_POWER_FALSE_KILL_INCONCLUSIVE_BOUNDARY_"
            "COVERAGE_AND_HARM_DETECTION_FOR_COUNT_AND_RATE"
        ),
        "selected_design_id": selected.design_id if selected is not None else None,
        "selection_status": (
            "ACCEPTABLE_DESIGN_SELECTED" if selected is not None else "NO_ACCEPTABLE_DESIGN_FOUND"
        ),
        "ordinary_precision_ok": ordinary_precision_ok,
        "critical_precision_ok": critical_precision_ok,
        "interval_procedure_valid_at_boundary": interval_procedure_valid,
        "boundary_calibration_status": cast(JsonValue, boundary_calibration_statuses),
        "icc_assumptions": {
            "baseline_site_icc": 0.15,
            "baseline_within_block_icc": 0.20,
            "baseline_status": "POSTULATED_NOT_PARTNER_ESTIMATE",
            "m2_exploratory_site_icc": 0.14788,
            "m2_exploratory_period_icc": 0.46308,
            "m2_values_are_not_partner_estimates": True,
            "pessimistic_site_icc": 0.30,
            "pessimistic_within_block_icc": 0.35,
            "single_hospital_group_generalization_claim": "forbidden",
        },
        "icc_sensitivity": {
            "selected_design_id": (
                pessimistic_selected.design_id if pessimistic_selected is not None else None
            ),
            "selection_status": (
                "ACCEPTABLE_DESIGN_SELECTED"
                if pessimistic_selected is not None
                else "NO_ACCEPTABLE_DESIGN_FOUND"
            ),
            "final_internal_episode_requirement": (
                pessimistic_selected.episode_count
                if pessimistic_selected is not None
                else "NO_ACCEPTABLE_DESIGN_FOUND"
            ),
            "scenarios": cast(JsonValue, pessimistic_results),
        },
        "inconclusive_real_experiment_decision": {
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
        },
        "m2_retrospective": retrospective_guardrail_decision(
            0.17307578440112872,
            0.1031056874381268,
            observed_design_effect=2.22192,
        ),
        "scenarios": cast(JsonValue, results),
    }
    payload["simulation_output_hash"] = _canonical_hash(payload)
    return payload
