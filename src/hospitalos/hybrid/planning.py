"""Bounded exact enumeration of immediate actions, evaluated over joint scenarios.

This v0 solves a deliberately small one-action decision problem. It is not a
multi-stage CP-SAT/MILP solver or an optimal hospital-wide scheduling claim.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, field_validator, model_validator

from hospitalos.operational.contract import Closed, Identifier, instant

from .journal import reconstruct
from .models import Action, FactEvent, State, action_errors
from .pathway import DischargeReadiness, readiness
from .scenarios import FutureAssumptions, sample_future
from .scoring import ResourcePressure, score
from .simulation import Assumptions, simulate


class PlanRequest(Closed):
    hospital_id: Identifier
    at: datetime
    expected_entities: Annotated[tuple[str, ...], Field(min_length=1, max_length=400)]
    events: Annotated[tuple[FactEvent, ...], Field(max_length=2000)]
    assumptions: Assumptions = Assumptions()
    future: FutureAssumptions | None = None
    max_age_minutes: Annotated[StrictInt, Field(gt=0, le=1440)] = 60
    horizon_minutes: Annotated[StrictInt, Field(gt=0, le=1440)] = 1440
    scenarios: Annotated[StrictInt, Field(ge=1, le=128)] = 32
    max_candidates: Annotated[StrictInt, Field(ge=2, le=32)] = 32
    seed: Annotated[StrictInt, Field(ge=0)] = 7
    tail_weight: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] = 0.25

    @field_validator("at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return instant(value)

    @model_validator(mode="after")
    def scenario_availability(self) -> Self:
        if self.future is not None and self.future.declared_at > self.at:
            raise ValueError("Future hypotheses must be declared by the decision origin")
        return self

    def state(self) -> State:
        return reconstruct(
            self.events, self.hospital_id, self.at, self.expected_entities, self.max_age_minutes
        )


class Candidate(Closed):
    action: Action
    mean_waiting_patient_minutes: float
    worst_decile_waiting_patient_minutes: float
    objective: float
    violations: tuple[str, ...]
    scenarios_with_unserved_demand: int
    max_waiting_at_end: int
    max_arrived: int = 0
    mean_staffed_pressure: float = 0
    mean_cleaning_pressure: float = 0
    mean_transport_pressure: float = 0
    mean_downstream_pressure: float = 0
    pressure_regression_scenarios: int = 0


class Plan(Closed):
    schema_version: Literal["HYBRID_PLAN_3"] = "HYBRID_PLAN_3"
    evidence: Literal["simulation_under_declared_assumptions"] = (
        "simulation_under_declared_assumptions"
    )
    decision: Literal["recommend", "no_change", "abstain"]
    plan_id: str
    hospital_id: str
    state_fingerprint: str
    created_at: datetime
    expires_at: datetime
    selected: Action
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    candidates: tuple[Candidate, ...]
    candidates_truncated: bool
    assumptions: Assumptions
    future: FutureAssumptions | None = None
    seed: int
    scenarios: int
    horizon_minutes: int
    tail_weight: float
    discharge_readiness: tuple[DischargeReadiness, ...]
    service_status: Literal[
        "not_assessed", "served_in_all_sampled_scenarios", "unserved_in_some_sampled_scenarios"
    ]


def enumerate_actions(state: State, limit: int) -> tuple[tuple[Action, ...], bool]:
    candidates = [Action(kind="no_op")]
    for bed in sorted(state.beds, key=lambda b: b.id):
        action = Action(kind="prioritize_cleaning", bed_id=bed.id)
        if not action_errors(state, action):
            candidates.append(action)
        if bed.occupant:
            action = Action(kind="request_transport", bed_id=bed.id, patient_id=bed.occupant)
            if not action_errors(state, action):
                candidates.append(action)
        for patient in sorted(state.patients, key=lambda p: (-p.priority, p.waiting_since, p.id)):
            action = Action(kind="reserve_bed", bed_id=bed.id, patient_id=patient.id)
            if not action_errors(state, action):
                candidates.append(action)
    return tuple(candidates[:limit]), len(candidates) > limit


@dataclass(frozen=True)
class Evaluation:
    candidate: Candidate
    pressure: tuple[ResourcePressure, ...]


def evaluate(state: State, action: Action, request: PlanRequest) -> Evaluation:
    losses = []
    waiting_at_end = []
    arrivals = []
    pressure = []
    violations: set[str] = set()
    for scenario in range(request.scenarios):
        future = sample_future(state, request.future, request.seed, scenario)
        trajectory = simulate(
            state,
            action,
            request.assumptions,
            seed=request.seed,
            scenario=scenario,
            horizon_minutes=request.horizon_minutes,
            future=future,
        )
        result = score(state, trajectory, expected_future=future)
        losses.append(result.waiting_patient_minutes)
        waiting_at_end.append(result.waiting_at_end)
        arrivals.append(result.arrived)
        pressure.append(result.pressure)
        violations.update(result.violations)
    mean = statistics.mean(losses)
    tail = statistics.mean(sorted(losses, reverse=True)[: max(1, math.ceil(len(losses) / 10))])
    candidate = Candidate(
        action=action,
        mean_waiting_patient_minutes=mean,
        worst_decile_waiting_patient_minutes=tail,
        objective=(1 - request.tail_weight) * mean + request.tail_weight * tail,
        violations=tuple(sorted(violations)),
        scenarios_with_unserved_demand=sum(n > 0 for n in waiting_at_end),
        max_waiting_at_end=max(waiting_at_end),
        max_arrived=max(arrivals),
        mean_staffed_pressure=statistics.mean(p.staffed_patient_minutes for p in pressure),
        mean_cleaning_pressure=statistics.mean(p.cleaning_team_minutes for p in pressure),
        mean_transport_pressure=statistics.mean(p.transport_team_minutes for p in pressure),
        mean_downstream_pressure=statistics.mean(p.downstream_place_minutes for p in pressure),
    )
    return Evaluation(candidate, tuple(pressure))


def plan(request: PlanRequest) -> Plan:
    state = request.state()
    no_op = Action(kind="no_op")
    parameters = request.model_dump(mode="json", exclude={"events"})
    parameters["fingerprint"] = state.fingerprint
    plan_id = hashlib.sha256(json.dumps(parameters, sort_keys=True).encode()).hexdigest()
    candidates: tuple[Candidate, ...] = ()
    truncated = False
    selected = no_op
    decision: Literal["recommend", "no_change", "abstain"] = "abstain"
    reasons = state.issues
    warnings = state.warnings
    service_status: Literal[
        "not_assessed", "served_in_all_sampled_scenarios", "unserved_in_some_sampled_scenarios"
    ] = "not_assessed"
    if not reasons:
        actions, truncated = enumerate_actions(state, request.max_candidates)
        evaluations = tuple(evaluate(state, action, request) for action in actions)
        baseline = evaluations[0]
        candidates = tuple(
            e.candidate.model_copy(
                update={
                    "pressure_regression_scenarios": sum(
                        any(
                            a > b
                            for a, b in zip(
                                actual.components(), reference.components(), strict=True
                            )
                        )
                        for actual, reference in zip(e.pressure, baseline.pressure, strict=True)
                    )
                }
            )
            for e in evaluations
        )
        # A mechanics failure invalidates the decision, rather than hiding a bad candidate.
        if any(c.violations for c in candidates):
            reasons = ("simulation_invariant_failure",)
        else:
            best = min(
                (c for c in candidates if c.pressure_regression_scenarios == 0),
                key=lambda c: (c.objective, c.action.kind != "no_op", c.action.key),
            )
            selected = best.action
            if any(
                (
                    best.mean_staffed_pressure,
                    best.mean_cleaning_pressure,
                    best.mean_transport_pressure,
                    best.mean_downstream_pressure,
                )
            ):
                warnings = (*warnings, "simulated_resource_pressure_requires_review")
            service_status = (
                "unserved_in_some_sampled_scenarios"
                if best.scenarios_with_unserved_demand
                else "served_in_all_sampled_scenarios"
            )
            decision = "no_change" if selected.kind == "no_op" else "recommend"
            reasons = (
                "no_admissible_simulated_improvement"
                if decision == "no_change"
                else "lower_simulated_waiting_cost_requires_human_approval",
            )
            if decision == "no_change" and any(
                c.objective < baseline.candidate.objective and c.pressure_regression_scenarios
                for c in candidates
            ):
                reasons = ("simulated_improvement_rejected_due_to_resource_pressure",)
    return Plan(
        decision=decision,
        plan_id=plan_id,
        hospital_id=state.hospital_id,
        state_fingerprint=state.fingerprint,
        created_at=state.at,
        expires_at=state.at + timedelta(minutes=15),
        selected=selected,
        reasons=reasons,
        warnings=warnings,
        candidates=candidates,
        candidates_truncated=truncated,
        assumptions=request.assumptions,
        future=request.future,
        seed=request.seed,
        scenarios=request.scenarios,
        horizon_minutes=request.horizon_minutes,
        tail_weight=request.tail_weight,
        discharge_readiness=readiness(state),
        service_status=service_status,
    )
