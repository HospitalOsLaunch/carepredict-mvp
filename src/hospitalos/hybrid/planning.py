"""Bounded exact enumeration of immediate actions, evaluated over joint scenarios.

This v0 solves a deliberately small one-action decision problem. It is not a
multi-stage CP-SAT/MILP solver or an optimal hospital-wide scheduling claim.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from datetime import datetime, timedelta
from typing import Annotated, Literal

from pydantic import Field, StrictInt, field_validator

from hospitalos.operational.contract import Closed, Identifier, instant

from .journal import reconstruct
from .models import Action, FactEvent, State, action_errors
from .scoring import score
from .simulation import Assumptions, simulate


class PlanRequest(Closed):
    hospital_id: Identifier
    at: datetime
    expected_entities: Annotated[tuple[str, ...], Field(min_length=1, max_length=400)]
    events: Annotated[tuple[FactEvent, ...], Field(max_length=2000)]
    assumptions: Assumptions = Assumptions()
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


class Plan(Closed):
    schema_version: Literal["HYBRID_PLAN_1"] = "HYBRID_PLAN_1"
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
    seed: int
    scenarios: int
    horizon_minutes: int
    tail_weight: float


def enumerate_actions(state: State, limit: int) -> tuple[tuple[Action, ...], bool]:
    candidates = [Action(kind="no_op")]
    for bed in sorted(state.beds, key=lambda b: b.id):
        action = Action(kind="prioritize_cleaning", bed_id=bed.id)
        if not action_errors(state, action):
            candidates.append(action)
        for patient in sorted(state.patients, key=lambda p: (-p.priority, p.waiting_since, p.id)):
            action = Action(kind="reserve_bed", bed_id=bed.id, patient_id=patient.id)
            if not action_errors(state, action):
                candidates.append(action)
    return tuple(candidates[:limit]), len(candidates) > limit


def evaluate(state: State, action: Action, request: PlanRequest) -> Candidate:
    losses = []
    violations: set[str] = set()
    for scenario in range(request.scenarios):
        trajectory = simulate(
            state,
            action,
            request.assumptions,
            seed=request.seed,
            scenario=scenario,
            horizon_minutes=request.horizon_minutes,
        )
        result = score(state, trajectory)
        losses.append(result.waiting_patient_minutes)
        violations.update(result.violations)
    mean = statistics.mean(losses)
    tail = statistics.mean(sorted(losses, reverse=True)[: max(1, math.ceil(len(losses) / 10))])
    return Candidate(
        action=action,
        mean_waiting_patient_minutes=mean,
        worst_decile_waiting_patient_minutes=tail,
        objective=(1 - request.tail_weight) * mean + request.tail_weight * tail,
        violations=tuple(sorted(violations)),
    )


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
    if not reasons:
        actions, truncated = enumerate_actions(state, request.max_candidates)
        candidates = tuple(evaluate(state, action, request) for action in actions)
        # A mechanics failure invalidates the decision, rather than hiding a bad candidate.
        if any(c.violations for c in candidates):
            reasons = ("simulation_invariant_failure",)
        else:
            best = min(
                candidates, key=lambda c: (c.objective, c.action.kind != "no_op", c.action.key)
            )
            selected = best.action
            decision = "no_change" if selected.kind == "no_op" else "recommend"
            reasons = (
                "no_simulated_improvement"
                if decision == "no_change"
                else "lower_simulated_waiting_cost_requires_human_approval",
            )
    return Plan(
        decision=decision,
        plan_id=plan_id,
        hospital_id=state.hospital_id,
        state_fingerprint=state.fingerprint,
        created_at=state.at,
        expires_at=state.at + timedelta(minutes=15),
        selected=selected,
        reasons=reasons,
        warnings=state.warnings,
        candidates=candidates,
        candidates_truncated=truncated,
        assumptions=request.assumptions,
        seed=request.seed,
        scenarios=request.scenarios,
        horizon_minutes=request.horizon_minutes,
        tail_weight=request.tail_weight,
    )
