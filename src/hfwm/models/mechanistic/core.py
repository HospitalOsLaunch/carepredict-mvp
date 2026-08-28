"""Explicit queue/conservation/semi-Markov comparator for HFWM-R0.

This module contains no fitting or optimisation path.  Every numerical constant is
part of :class:`MechanisticConfig`, and the component identity is derived from the
canonical configuration.  The model is deliberately action agnostic: accepting an
action would imply an observability claim that HFWM-R0 is not allowed to make.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import cast

from hfwm.contracts import (
    ActionObservation,
    BeliefState,
    ComponentIdentity,
    StateEncoderInput,
    TokenBatch,
    TrajectoryRollout,
    TrajectoryScore,
    TransitionPrediction,
)
from hfwm.contracts.serialization import JSONValue

_VARIABLES = ("occupancy", "inflow", "discharges", "staffing", "pressure")
_TOLERANCE = 1e-9


@dataclass(frozen=True, slots=True)
class MechanisticConfig:
    """Pre-registered constants for the non-learned comparator.

    ``stay_hazards`` are conditional discharge probabilities by elapsed-stay
    cohort.  Survivors in the last cohort remain there, making the transition
    explicitly semi-Markov rather than a one-rate stock equation.
    """

    step_hours: float = 1.0
    default_capacity: float = 100.0
    default_staffing: float = 20.0
    initial_cohort_weights: tuple[float, ...] = (0.18, 0.22, 0.24, 0.20, 0.16)
    stay_hazards: tuple[float, ...] = (0.03, 0.06, 0.10, 0.16, 0.22)
    occupancy_pressure_weight: float = 0.70
    staffing_pressure_weight: float = 0.30
    nominal_patients_per_staff: float = 4.0
    base_uncertainty: float = 0.025
    uncertainty_growth_per_step: float = 0.018
    missingness_penalty: float = 0.12
    delay_penalty_per_hour: float = 0.006
    stochastic_scale: float = 0.20

    def __post_init__(self) -> None:
        if self.step_hours <= 0.0:
            raise ValueError("step_hours must be positive")
        if self.default_capacity <= 0.0 or self.default_staffing < 0.0:
            raise ValueError("default capacity/staffing are invalid")
        if not self.initial_cohort_weights:
            raise ValueError("at least one stay cohort is required")
        if len(self.initial_cohort_weights) != len(self.stay_hazards):
            raise ValueError("cohort weights and hazards must have the same length")
        if any(weight < 0.0 for weight in self.initial_cohort_weights):
            raise ValueError("cohort weights must be non-negative")
        if not math.isclose(sum(self.initial_cohort_weights), 1.0, abs_tol=_TOLERANCE):
            raise ValueError("initial cohort weights must sum to one")
        if any(hazard < 0.0 or hazard > 1.0 for hazard in self.stay_hazards):
            raise ValueError("stay hazards must be probabilities")
        if not math.isclose(
            self.occupancy_pressure_weight + self.staffing_pressure_weight,
            1.0,
            abs_tol=_TOLERANCE,
        ):
            raise ValueError("pressure weights must sum to one")
        if self.nominal_patients_per_staff <= 0.0:
            raise ValueError("nominal_patients_per_staff must be positive")
        if min(
            self.base_uncertainty,
            self.uncertainty_growth_per_step,
            self.missingness_penalty,
            self.delay_penalty_per_hour,
            self.stochastic_scale,
        ) < 0.0:
            raise ValueError("uncertainty constants must be non-negative")

    def semantic_hash(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return cast(Mapping[str, object], value)


def _state_payload(state: BeliefState) -> Mapping[str, object]:
    return _mapping(state.value, "belief state value")


def _float_field(payload: Mapping[str, object], key: str) -> float:
    result = _number(payload.get(key))
    if result is None:
        raise ValueError(f"belief state field {key!r} must be a finite number")
    return result


def _cohort_field(payload: Mapping[str, object]) -> list[float]:
    raw = payload.get("stay_cohorts")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ValueError("belief state stay_cohorts must be a sequence")
    cohorts: list[float] = []
    for item in raw:
        number = _number(item)
        if number is None:
            raise ValueError("stay cohorts must contain finite numbers")
        cohorts.append(number)
    if not cohorts:
        raise ValueError("belief state must contain stay cohorts")
    return cohorts


def _mask_mapping(batch: TokenBatch) -> Mapping[str, object]:
    if isinstance(batch.attention_mask, Mapping):
        return cast(Mapping[str, object], batch.attention_mask)
    return {}


def _values_mapping(batch: TokenBatch) -> Mapping[str, object]:
    if isinstance(batch.values, Mapping):
        return cast(Mapping[str, object], batch.values)
    raise ValueError("mechanistic observations.values must be a variable mapping")


def _delay_hours(
    batch: TokenBatch,
    recording_process: Mapping[str, JSONValue],
) -> float:
    candidates = (
        batch.metadata.get("observation_delay_hours"),
        recording_process.get("observation_delay_hours"),
        recording_process.get("delay_hours"),
    )
    for candidate in candidates:
        number = _number(candidate)
        if number is not None:
            return max(0.0, number)
    return 0.0


def _pressure(
    occupancy: float,
    capacity: float,
    staffing: float,
    config: MechanisticConfig,
) -> float:
    occupancy_load = occupancy / max(capacity, _TOLERANCE)
    staffing_load = occupancy / max(
        staffing * config.nominal_patients_per_staff,
        _TOLERANCE,
    )
    return max(
        0.0,
        config.occupancy_pressure_weight * occupancy_load
        + config.staffing_pressure_weight * staffing_load,
    )


def _uncertainty_payload(
    config: MechanisticConfig,
    *,
    step: int,
    missing: Sequence[str],
    delay_hours: float,
) -> dict[str, object]:
    scalar = (
        config.base_uncertainty
        + config.uncertainty_growth_per_step * math.sqrt(max(0, step))
        + config.missingness_penalty * len(missing)
        + config.delay_penalty_per_hour * delay_hours
    )
    return {
        "scalar": scalar,
        "by_variable": dict.fromkeys(_VARIABLES, scalar),
        "missing_variables": list(missing),
        "observation_delay_hours": delay_hours,
    }


def _action_guard(actions: Sequence[ActionObservation]) -> None:
    if actions:
        raise ValueError(
            "ACTION_CONDITIONING_NOT_IDENTIFIABLE: mechanistic HFWM-R0 rejects actions"
        )


def _audit_violations(payload: Mapping[str, object]) -> int:
    violations = 0
    occupancy = _float_field(payload, "occupancy")
    capacity = _float_field(payload, "capacity")
    for variable in _VARIABLES:
        if _float_field(payload, variable) < -_TOLERANCE:
            violations += 1
    if occupancy > capacity + _TOLERANCE:
        violations += 1
    audit = payload.get("conservation_audit")
    if isinstance(audit, Mapping):
        residual = _number(audit.get("residual"))
        if residual is None or abs(residual) > _TOLERANCE:
            violations += 1
    else:
        violations += 1
    return violations


def _trajectory_rows(rollout: TrajectoryRollout) -> list[Mapping[str, object]]:
    trajectories = rollout.state_trajectories
    if not isinstance(trajectories, Sequence) or isinstance(trajectories, (str, bytes)):
        raise ValueError("rollout state trajectories must be a sequence")
    if not trajectories:
        return []
    first = trajectories[0]
    if isinstance(first, Mapping):
        return [cast(Mapping[str, object], row) for row in trajectories]
    if isinstance(first, Sequence) and not isinstance(first, (str, bytes)):
        samples = [cast(Sequence[object], sample) for sample in trajectories]
        row_count = len(samples[0])
        if any(len(sample) != row_count for sample in samples):
            raise ValueError("sampled trajectories have inconsistent horizons")
        averaged: list[Mapping[str, object]] = []
        for step in range(row_count):
            rows = [_mapping(sample[step], "sample state") for sample in samples]
            reference = rows[0]
            averaged.append(
                {
                    variable: sum(_float_field(row, variable) for row in rows) / len(rows)
                    for variable in (*_VARIABLES, "capacity")
                }
                | {"step": reference.get("step", step + 1)}
            )
        return averaged
    raise ValueError("rollout state trajectory rows must be mappings")


def hard_violation_rate(rollout: TrajectoryRollout) -> float:
    """Return the fraction of generated states with any hard constraint breach."""

    trajectories = rollout.state_trajectories
    if not isinstance(trajectories, Sequence) or isinstance(trajectories, (str, bytes)):
        raise ValueError("rollout state trajectories must be a sequence")
    rows: list[Mapping[str, object]] = []
    for item in trajectories:
        if isinstance(item, Mapping):
            rows.append(cast(Mapping[str, object], item))
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
            rows.extend(_mapping(row, "sample state") for row in item)
        else:
            raise ValueError("rollout state trajectory rows must be mappings")
    if not rows:
        return 0.0
    return sum(_audit_violations(row) > 0 for row in rows) / len(rows)


class MechanisticQueueSemiMarkov:
    """Non-learned DynamicsCore comparator with auditable conservation."""

    def __init__(self, config: MechanisticConfig | None = None) -> None:
        self.config = config or MechanisticConfig()
        self.identity = ComponentIdentity(
            component_type="DynamicsCore",
            implementation_id="mechanistic_queue_semimarkov",
            contract_version="hfwm.architecture.v1",
            implementation_version="r0",
            artifact_hash=self.config.semantic_hash(),
        )

    def infer_state(self, inputs: StateEncoderInput) -> BeliefState:
        values = _values_mapping(inputs.observations)
        mask = _mask_mapping(inputs.observations)
        defaults = {
            "occupancy": 0.0,
            "inflow": 0.0,
            "discharges": 0.0,
            "staffing": self.config.default_staffing,
            "pressure": 0.0,
            "capacity": self.config.default_capacity,
        }
        extracted: dict[str, float] = {}
        missing: list[str] = []
        corrected: list[str] = []
        for variable, default in defaults.items():
            observed = _number(values.get(variable))
            observed_mask = mask.get(variable, True)
            if observed is None or observed_mask is False or observed_mask == 0:
                extracted[variable] = default
                missing.append(variable)
            else:
                extracted[variable] = observed

        for variable in ("occupancy", "inflow", "discharges", "staffing"):
            if extracted[variable] < 0.0:
                extracted[variable] = 0.0
                corrected.append(variable)
        if extracted["capacity"] <= 0.0:
            extracted["capacity"] = self.config.default_capacity
            corrected.append("capacity")
        if extracted["occupancy"] > extracted["capacity"]:
            extracted["occupancy"] = extracted["capacity"]
            corrected.append("occupancy")
        if "pressure" in missing or extracted["pressure"] < 0.0:
            extracted["pressure"] = _pressure(
                extracted["occupancy"],
                extracted["capacity"],
                extracted["staffing"],
                self.config,
            )
            if "pressure" not in missing:
                corrected.append("pressure")

        cohorts = [
            extracted["occupancy"] * weight for weight in self.config.initial_cohort_weights
        ]
        delay = _delay_hours(inputs.observations, inputs.recording_process)
        as_of = (
            inputs.observations.available_at[-1]
            if inputs.observations.available_at
            else str(inputs.context.get("as_of", "UNKNOWN_AS_OF"))
        )
        provenance: list[Mapping[str, JSONValue]] = [
            {
                "component": "mechanistic_queue_semimarkov",
                "mode": "fixed_preregistered_constants",
                "action_conditioning": "ACTION_CONDITIONING_NOT_IDENTIFIABLE",
            }
        ]
        if missing:
            provenance.append(
                {
                    "signal": "masked_or_missing",
                    "variables": cast(JSONValue, list(missing)),
                }
            )
        if delay > 0.0:
            provenance.append({"signal": "observation_delay", "delay_hours": delay})
        if corrected:
            provenance.append(
                {
                    "signal": "hard_constraint_projection",
                    "variables": cast(JSONValue, list(corrected)),
                }
            )
        value: dict[str, object] = {
            **extracted,
            "stay_cohorts": cohorts,
            "step": 0,
            "missing_variables": list(missing),
            "observation_delay_hours": delay,
        }
        uncertainty = _uncertainty_payload(
            self.config,
            step=0,
            missing=missing,
            delay_hours=delay,
        )
        return BeliefState(
            value=value,
            state_uncertainty=uncertainty,
            entity_states={"hospital": value},
            hierarchical_states={"hospital": value},
            provenance=tuple(provenance),
            as_of=as_of,
        )

    def update_state(
        self,
        state: BeliefState,
        observations: TokenBatch,
        context: Mapping[str, JSONValue],
    ) -> BeliefState:
        previous = _state_payload(state)
        observed = _values_mapping(observations)
        mask = _mask_mapping(observations)
        merged: dict[str, object] = {
            variable: previous[variable] for variable in (*_VARIABLES, "capacity")
        }
        missing: list[str] = []
        for variable in (*_VARIABLES, "capacity"):
            number = _number(observed.get(variable))
            if number is None or mask.get(variable, True) is False or mask.get(variable) == 0:
                missing.append(variable)
            else:
                merged[variable] = number
        batch = TokenBatch(
            values=merged,
            attention_mask=dict.fromkeys(merged, True),
            entity_ids=observations.entity_ids,
            event_ids=observations.event_ids,
            available_at=observations.available_at or (state.as_of,),
            provenance=observations.provenance,
            metadata=observations.metadata,
        )
        refreshed = self.infer_state(
            StateEncoderInput(
                observations=batch,
                history=(),
                entity_graph={},
                recording_process=context,
                context=context,
                site_metadata={},
            )
        )
        if not missing:
            return refreshed
        refreshed_value = dict(_state_payload(refreshed))
        refreshed_value["missing_variables"] = missing
        delay = _delay_hours(observations, context)
        uncertainty = _uncertainty_payload(
            self.config,
            step=0,
            missing=missing,
            delay_hours=delay,
        )
        carry_forward_provenance: Mapping[str, JSONValue] = {
            "signal": "state_update_carried_forward",
            "variables": cast(JSONValue, list(missing)),
        }
        provenance = tuple(refreshed.provenance) + (carry_forward_provenance,)
        return BeliefState(
            value=refreshed_value,
            state_uncertainty=uncertainty,
            entity_states={"hospital": refreshed_value},
            hierarchical_states={"hospital": refreshed_value},
            provenance=provenance,
            as_of=refreshed.as_of,
        )

    def _advance_payload(
        self,
        payload: Mapping[str, object],
        *,
        rng: random.Random | None = None,
    ) -> tuple[dict[str, object], dict[str, object]]:
        capacity = max(_TOLERANCE, _float_field(payload, "capacity"))
        occupancy = min(capacity, max(0.0, _float_field(payload, "occupancy")))
        inflow_rate = max(0.0, _float_field(payload, "inflow"))
        staffing = max(0.0, _float_field(payload, "staffing"))
        cohorts = _cohort_field(payload)
        if len(cohorts) != len(self.config.stay_hazards):
            raise ValueError("belief state cohort count does not match pre-registered config")

        offered_inflow = inflow_rate * self.config.step_hours
        expected_by_cohort = [
            max(0.0, cohort) * hazard
            for cohort, hazard in zip(cohorts, self.config.stay_hazards, strict=True)
        ]
        if rng is None:
            discharge_by_cohort = expected_by_cohort
        else:
            offered_inflow = max(
                0.0,
                rng.gauss(
                    offered_inflow,
                    self.config.stochastic_scale * math.sqrt(max(offered_inflow, 1.0)),
                ),
            )
            discharge_by_cohort = [
                min(
                    max(0.0, cohort),
                    max(
                        0.0,
                        rng.gauss(
                            expected,
                            self.config.stochastic_scale * math.sqrt(max(expected, 1.0)),
                        ),
                    ),
                )
                for cohort, expected in zip(cohorts, expected_by_cohort, strict=True)
            ]

        discharges = min(occupancy, sum(discharge_by_cohort))
        available_capacity = max(0.0, capacity - (occupancy - discharges))
        admitted_inflow = min(offered_inflow, available_capacity)
        rejected_inflow = max(0.0, offered_inflow - admitted_inflow)

        survivors = [
            max(0.0, cohort - discharged)
            for cohort, discharged in zip(cohorts, discharge_by_cohort, strict=True)
        ]
        next_cohorts = [0.0 for _ in cohorts]
        next_cohorts[0] = admitted_inflow
        for index, survivor in enumerate(survivors):
            destination = min(index + 1, len(next_cohorts) - 1)
            next_cohorts[destination] += survivor
        next_occupancy = sum(next_cohorts)
        conservation_expected = occupancy + admitted_inflow - discharges
        residual = next_occupancy - conservation_expected
        step = int(_float_field(payload, "step")) + 1 if "step" in payload else 1
        next_pressure = _pressure(next_occupancy, capacity, staffing, self.config)
        raw_missing = payload.get("missing_variables", [])
        carried_missing = (
            [item for item in raw_missing if isinstance(item, str)]
            if isinstance(raw_missing, Sequence) and not isinstance(raw_missing, (str, bytes))
            else []
        )
        next_payload: dict[str, object] = {
            "occupancy": next_occupancy,
            "inflow": offered_inflow / self.config.step_hours,
            "discharges": discharges / self.config.step_hours,
            "staffing": staffing,
            "pressure": next_pressure,
            "capacity": capacity,
            "stay_cohorts": next_cohorts,
            "step": step,
            "missing_variables": carried_missing,
            "observation_delay_hours": _number(payload.get("observation_delay_hours")) or 0.0,
            "conservation_audit": {
                "previous_occupancy": occupancy,
                "offered_inflow": offered_inflow,
                "admitted_inflow": admitted_inflow,
                "rejected_inflow": rejected_inflow,
                "discharges": discharges,
                "expected_next_occupancy": conservation_expected,
                "actual_next_occupancy": next_occupancy,
                "residual": residual,
            },
        }
        events: dict[str, object] = {
            "offered_inflow": offered_inflow,
            "admitted_inflow": admitted_inflow,
            "rejected_inflow": rejected_inflow,
            "discharges": discharges,
        }
        return next_payload, events

    def predict_next(
        self,
        state: BeliefState,
        actions: Sequence[ActionObservation],
        context: Mapping[str, JSONValue],
    ) -> TransitionPrediction:
        del context
        _action_guard(actions)
        payload, events = self._advance_payload(_state_payload(state))
        missing = cast(list[str], payload["missing_variables"])
        uncertainty = _uncertainty_payload(
            self.config,
            step=int(_float_field(payload, "step")),
            missing=missing,
            delay_hours=_float_field(payload, "observation_delay_hours"),
        )
        audit = _mapping(payload["conservation_audit"], "conservation audit")
        return TransitionPrediction(
            next_state_distribution=payload,
            event_distribution=events,
            uncertainty=uncertainty,
            constraint_context={
                "capacity_enforced": True,
                "non_negativity_enforced": True,
                "conservation_residual": cast(JSONValue, audit["residual"]),
                "action_conditioning": "ACTION_CONDITIONING_NOT_IDENTIFIABLE",
            },
            horizon_steps=1,
        )

    def rollout(
        self,
        state: BeliefState,
        actions: Sequence[ActionObservation],
        context: Mapping[str, JSONValue],
        horizon_steps: int,
    ) -> TrajectoryRollout:
        del context
        _action_guard(actions)
        if horizon_steps < 1:
            raise ValueError("horizon_steps must be at least one")
        payload = dict(_state_payload(state))
        states: list[dict[str, object]] = []
        events: list[dict[str, object]] = []
        uncertainty: list[dict[str, object]] = []
        for _ in range(horizon_steps):
            payload, step_events = self._advance_payload(payload)
            states.append(payload)
            events.append(step_events)
            missing = cast(list[str], payload["missing_variables"])
            uncertainty.append(
                _uncertainty_payload(
                    self.config,
                    step=int(_float_field(payload, "step")),
                    missing=missing,
                    delay_hours=_float_field(payload, "observation_delay_hours"),
                )
            )
        return TrajectoryRollout(
            state_trajectories=states,
            event_trajectories=events,
            uncertainty_by_horizon=uncertainty,
            free_running=True,
            horizon_steps=horizon_steps,
            provenance=(
                {
                    "component": "mechanistic_queue_semimarkov",
                    "mode": "free_running_fixed_constants",
                    "action_conditioning": "ACTION_CONDITIONING_NOT_IDENTIFIABLE",
                },
            ),
        )

    def sample_futures(
        self,
        state: BeliefState,
        actions: Sequence[ActionObservation],
        context: Mapping[str, JSONValue],
        horizon_steps: int,
        sample_count: int,
        seed: int,
    ) -> TrajectoryRollout:
        del context
        _action_guard(actions)
        if horizon_steps < 1 or sample_count < 1:
            raise ValueError("horizon_steps and sample_count must be at least one")
        rng = random.Random(seed)
        sampled_states: list[list[dict[str, object]]] = []
        sampled_events: list[list[dict[str, object]]] = []
        for _ in range(sample_count):
            payload = dict(_state_payload(state))
            states: list[dict[str, object]] = []
            events: list[dict[str, object]] = []
            for _ in range(horizon_steps):
                payload, step_events = self._advance_payload(payload, rng=rng)
                states.append(payload)
                events.append(step_events)
            sampled_states.append(states)
            sampled_events.append(events)
        base_payload = _state_payload(state)
        missing = cast(list[str], base_payload.get("missing_variables", []))
        delay = _number(base_payload.get("observation_delay_hours")) or 0.0
        uncertainty = [
            _uncertainty_payload(
                self.config,
                step=step,
                missing=missing,
                delay_hours=delay,
            )
            for step in range(1, horizon_steps + 1)
        ]
        return TrajectoryRollout(
            state_trajectories=sampled_states,
            event_trajectories=sampled_events,
            uncertainty_by_horizon=uncertainty,
            free_running=True,
            horizon_steps=horizon_steps,
            provenance=(
                {
                    "component": "mechanistic_queue_semimarkov",
                    "mode": "seeded_stochastic_free_running",
                    "seed": seed,
                    "sample_count": sample_count,
                    "action_conditioning": "ACTION_CONDITIONING_NOT_IDENTIFIABLE",
                },
            ),
        )

    def score_observed_trajectory(
        self,
        rollout: TrajectoryRollout,
        observed: Sequence[Mapping[str, JSONValue]],
    ) -> TrajectoryScore:
        predictions = _trajectory_rows(rollout)
        if len(observed) > len(predictions):
            raise ValueError("observed trajectory exceeds rollout horizon")
        per_step: list[float] = []
        evaluated_values = 0
        masked_values = 0
        for step, observation in enumerate(observed):
            prediction = predictions[step]
            raw_mask = observation.get("mask", {})
            mask = raw_mask if isinstance(raw_mask, Mapping) else {}
            squared_errors: list[float] = []
            capacity = max(_float_field(prediction, "capacity"), 1.0)
            for variable in _VARIABLES:
                if mask.get(variable, True) is False or mask.get(variable) == 0:
                    masked_values += 1
                    continue
                actual = _number(observation.get(variable))
                if actual is None:
                    masked_values += 1
                    continue
                predicted = _float_field(prediction, variable)
                scale = capacity if variable in {"occupancy", "inflow", "discharges"} else max(
                    abs(predicted),
                    1.0,
                )
                squared_errors.append(((actual - predicted) / scale) ** 2)
                evaluated_values += 1
            per_step.append(-sum(squared_errors) / len(squared_errors) if squared_errors else 0.0)
        aggregate = sum(per_step) / len(per_step) if per_step else 0.0
        return TrajectoryScore(
            aggregate_score=aggregate,
            per_step_scores=per_step,
            scoring_rule="masked_negative_scaled_squared_error_v1",
            metadata={
                "evaluated_values": evaluated_values,
                "masked_values": masked_values,
                "action_conditioning": "ACTION_CONDITIONING_NOT_IDENTIFIABLE",
                "hard_violation_rate": hard_violation_rate(rollout),
            },
        )
