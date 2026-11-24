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
from itertools import combinations, zip_longest
from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, field_validator, model_validator

from hospitalos.operational.contract import Closed, Identifier, instant

from .journal import reconstruct
from .models import Action, FactEvent, State, action_errors, bundle_errors
from .multiday import assess_horizon, paired_future
from .outlook import HorizonCheck
from .pathway import DischargeReadiness, readiness
from .preparation import PreparationForecasts, validate_preparation
from .scenarios import FutureAssumptions
from .scoring import ResourcePressure, score
from .simulation import Assumptions, simulate


class PlanRequest(Closed):
    hospital_id: Identifier
    at: datetime
    unit_id: Identifier | None = None
    expected_entities: Annotated[tuple[str, ...], Field(min_length=1, max_length=400)]
    events: Annotated[tuple[FactEvent, ...], Field(max_length=2000)]
    assumptions: Assumptions = Assumptions()
    future: FutureAssumptions | None = None
    preparation: PreparationForecasts | None = None
    max_age_minutes: Annotated[StrictInt, Field(gt=0, le=1440)] = 60
    horizon_minutes: Annotated[StrictInt, Field(gt=0, le=10080)] = 1440
    # Up to this many immediate actions applied together (1 = the historical one-action
    # decision). Steps are added greedily, each evaluated jointly with the steps before it.
    max_bundle: Annotated[StrictInt, Field(ge=1, le=4)] = 1
    scenarios: Annotated[StrictInt, Field(ge=1, le=128)] = 32
    max_candidates: Annotated[StrictInt, Field(ge=2, le=32)] = 32
    seed: Annotated[StrictInt, Field(ge=0)] = 7
    tail_weight: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] = 0.25

    @field_validator("horizon_minutes")
    @classmethod
    def supported_horizon(cls, value: int) -> int:
        if value > 1440 and value not in {4320, 10080}:
            raise ValueError("Extended horizons are 3 or 7 days")
        return value

    @field_validator("at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return instant(value)

    @model_validator(mode="after")
    def scenario_availability(self) -> Self:
        if self.unit_id and {
            e.fact.id
            for e in self.events
            if e.fact.kind == "unit"
            and e.available_at <= self.at
            and e.hospital_id == self.hospital_id
        } - {self.unit_id}:
            raise ValueError("Unit planning requires a single beneficiary unit")
        if self.future is not None and self.future.declared_at > self.at:
            raise ValueError("Future hypotheses must be declared by the decision origin")
        if self.preparation is not None:
            validate_preparation(self.state(), self.preparation)
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


class PlanWindow(Closed):
    minutes: int
    baseline_wait: float
    selected_wait: float
    unserved_scenarios: int
    change_ratio: float | None
    saved_wait: float
    until: datetime


class ActionTiming(Closed):
    starts_at: datetime
    ends_at: datetime | None = None
    skill: str | None = None
    lender: str | None = None


def timing(state: State, action: Action) -> ActionTiming:
    for schedule in state.schedules:
        if action.kind == "reinforce":
            for offer in schedule.offers:
                o = offer.option
                if o.option_id == action.slot_id:
                    return ActionTiming(
                        starts_at=o.start, ends_at=o.end, skill=o.skill, lender=o.lending_unit
                    )
        if action.kind == "prepare_admission":
            for b in schedule.admissions:
                if b.request.request_id == action.slot_id:
                    return ActionTiming(starts_at=b.window_start, ends_at=b.window_end)
    return ActionTiming(starts_at=state.at)


class Plan(Closed):
    action_timing: tuple[ActionTiming, ...] = ()
    unit_id: Identifier | None = None
    windows: tuple[PlanWindow, ...] = ()
    horizons: tuple[HorizonCheck, ...] = ()
    requested_horizon_minutes: int | None = None

    schema_version: Literal["HYBRID_PLAN_4", "HYBRID_PLAN_5", "HYBRID_UNIT_PLAN_1"] = (
        "HYBRID_PLAN_4"
    )
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
    preparation: PreparationForecasts | None = None
    # Combination of immediate actions evaluated together (first step = selected). Empty when
    # the decision is a single action. Marginal gains: decrease of the mean waiting
    # (patient-minutes) brought by each step, in order, the first one relative to doing nothing.
    bundle: tuple[Action, ...] = ()
    bundle_evaluation: Candidate | None = None
    bundle_marginal_minutes: tuple[float, ...] = ()
    seed: int
    scenarios: int
    horizon_minutes: int
    tail_weight: float
    discharge_readiness: tuple[DischargeReadiness, ...]
    service_status: Literal[
        "not_assessed", "served_in_all_sampled_scenarios", "unserved_in_some_sampled_scenarios"
    ]

    @model_validator(mode="after")
    def forecast_version(self) -> Self:
        continuous = (
            self.preparation is not None
            and self.preparation.schema_version == "PREPARATION_FORECAST_2"
        )
        if (
            self.schema_version != "HYBRID_UNIT_PLAN_1"
            and (self.schema_version == "HYBRID_PLAN_5") != continuous
        ):
            raise ValueError("Plan/forecast version mismatch")
        return self


def enumerate_actions(
    state: State, limit: int, horizon_minutes: int = 1440
) -> tuple[tuple[Action, ...], bool]:
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
    if state.schedules:
        end = state.at + timedelta(minutes=horizon_minutes)
        for schedule in state.schedules:
            for offer in sorted(schedule.offers, key=lambda o: o.option.option_id):
                action = Action(kind="reinforce", slot_id=offer.option.option_id)
                if offer.option.start < end and not action_errors(state, action):
                    candidates.append(action)
            for booking in sorted(schedule.admissions, key=lambda b: b.request.request_id):
                if booking.request.expected_arrival >= end:
                    continue
                for bed in sorted(state.beds, key=lambda b: b.id):
                    action = Action(
                        kind="prepare_admission", slot_id=booking.request.request_id, bed_id=bed.id
                    )
                    if not action_errors(state, action):
                        candidates.append(action)
        # Preserve space for each family under the global computation budget.
        groups = [
            [a for a in candidates if a.kind == kind]
            for kind in (
                "request_transport",
                "prioritize_cleaning",
                "reserve_bed",
                "reinforce",
                "prepare_admission",
            )
        ]
        candidates = [candidates[0], *(a for row in zip_longest(*groups) for a in row if a)]
    return tuple(candidates[:limit]), len(candidates) > limit


@dataclass(frozen=True)
class Evaluation:
    candidate: Candidate
    pressure: tuple[ResourcePressure, ...]


def evaluate(
    state: State,
    action: Action | tuple[Action, ...],
    request: PlanRequest,
    *,
    multiday: bool | None = None,
) -> Evaluation:
    multiday = request.horizon_minutes > 1440 if multiday is None else multiday
    losses = []
    waiting_at_end = []
    arrivals = []
    pressure = []
    violations: set[str] = set()
    for scenario in range(request.scenarios):
        future = paired_future(
            state,
            request.future,
            request.seed,
            scenario,
            request.horizon_minutes,
            multiday=multiday,
        )
        trajectory = simulate(
            state,
            action,
            request.assumptions,
            seed=request.seed,
            scenario=scenario,
            horizon_minutes=request.horizon_minutes,
            future=future,
            preparation=request.preparation,
            multiday=multiday,
        )
        result = score(
            state,
            trajectory,
            expected_future=future,
            actions=(action,) if isinstance(action, Action) else action,
        )
        losses.append(result.waiting_patient_minutes)
        waiting_at_end.append(result.waiting_at_end)
        arrivals.append(result.arrived)
        pressure.append(result.pressure)
        violations.update(result.violations)
    mean = statistics.mean(losses)
    tail = statistics.mean(sorted(losses, reverse=True)[: max(1, math.ceil(len(losses) / 10))])
    candidate = Candidate(
        action=action if isinstance(action, Action) else action[0],
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


def _regressions(evaluation: Evaluation, baseline: Evaluation) -> int:
    return sum(
        any(a > b for a, b in zip(actual.components(), reference.components(), strict=True))
        for actual, reference in zip(evaluation.pressure, baseline.pressure, strict=True)
    )


def _bundle(
    state: State,
    request: PlanRequest,
    best: Candidate,
    baseline: Evaluation,
    candidates: tuple[Candidate, ...],
) -> tuple[tuple[Action, ...], Candidate | None, tuple[float, ...]]:
    """Greedy combination of immediate actions, each step evaluated jointly with the steps
    before it on the same paired scenarios. A step is kept only if it lowers the objective by
    a material amount (1 % of doing nothing, at least one patient-minute) without any
    resource-pressure regression against doing nothing. Not an optimality claim: a bounded,
    explainable search over the admissible immediate actions."""
    material = max(1.0, 0.01 * baseline.candidate.objective)
    # Complements need not help alone: a cleaning can matter only once a departure is
    # requested. Their worth is judged jointly, step by step.
    useful = [
        c.action
        for c in sorted(candidates, key=lambda c: (c.objective, c.action.key))
        if c.action.kind != "no_op" and c.action != best.action
    ]
    steps: tuple[Action, ...] = (best.action,)
    current = best
    # Shown to people: mean waiting removed by each step (the selection itself uses the
    # objective, which also weighs the worst scenarios).
    marginals = [
        baseline.candidate.mean_waiting_patient_minutes - best.mean_waiting_patient_minutes
    ]
    if best.action.kind == "no_op":
        # Two neutral actions can be useful only together. Evaluate all admissible seed pairs.
        winners = []
        singles = {c.action.key: c for c in candidates}
        for left, right in combinations(useful, 2):
            if bundle_errors(state, (left, right)):
                continue
            ev = evaluate(state, (left, right), request)
            if (
                not ev.candidate.violations
                and not _regressions(ev, baseline)
                and baseline.candidate.objective - ev.candidate.objective >= material
            ):
                winners.append(
                    (ev.candidate.objective, left.key, right.key, left, right, ev.candidate)
                )
        if not winners:
            return (), None, ()
        _, _, _, left, right, current = min(winners, key=lambda t: t[:3])
        steps = (left, right)
        intermediate = singles[left.key].mean_waiting_patient_minutes
        marginals = [
            baseline.candidate.mean_waiting_patient_minutes - intermediate,
            intermediate - current.mean_waiting_patient_minutes,
        ]
    while len(steps) < request.max_bundle:
        trials: list[tuple[float, str, Action, Evaluation]] = []
        for action in useful:
            if action in steps or bundle_errors(state, (*steps, action)):
                continue
            evaluation = evaluate(state, (*steps, action), request)
            if evaluation.candidate.violations or _regressions(evaluation, baseline):
                continue
            trials.append((evaluation.candidate.objective, action.key, action, evaluation))
        if not trials:
            break
        objective, _, action, evaluation = min(trials, key=lambda t: (t[0], t[1]))
        if current.objective - objective < material:
            break
        marginals.append(
            current.mean_waiting_patient_minutes - evaluation.candidate.mean_waiting_patient_minutes
        )
        steps = (*steps, action)
        current = evaluation.candidate
    if len(steps) == 1:
        return (), None, ()
    return steps, current, tuple(marginals)


def plan(request: PlanRequest) -> Plan:
    state = request.state()
    if request.preparation is not None:
        validate_preparation(state, request.preparation)
    no_op = Action(kind="no_op")
    # max_bundle at its default is left out: one-action plans keep their historical ids.
    parameters = request.model_dump(
        mode="json", exclude={"events", "max_bundle"} if request.max_bundle == 1 else {"events"}
    )
    if request.unit_id is None:
        parameters.pop("unit_id")
    unified = bool(
        request.unit_id or state.schedules or state.outlooks or request.horizon_minutes > 1440
    )
    if unified:
        parameters["profile"] = "HYBRID_UNIT_PLAN_1"
    parameters["fingerprint"] = state.fingerprint
    plan_id = hashlib.sha256(json.dumps(parameters, sort_keys=True).encode()).hexdigest()
    requested = request.horizon_minutes
    unit = request.unit_id or (state.units[0].id if len(state.units) == 1 else None)
    horizons = tuple(assess_horizon(state, unit, d) for d in (3, 7)) if unit else ()
    if requested > 1440:
        eligible = [
            h.days * 1440
            for h in horizons
            if h.data_ready and h.qualified and h.days * 1440 <= requested
        ]
        request = request.model_copy(update={"horizon_minutes": max([1440, *eligible])})
        # The same data can acquire a new qualification in a later deployment.
        parameters["horizon_policy"] = {str(h.days): [h.data_ready, h.qualified] for h in horizons}
        plan_id = hashlib.sha256(json.dumps(parameters, sort_keys=True).encode()).hexdigest()
    candidates: tuple[Candidate, ...] = ()
    truncated = False
    selected = no_op
    bundle: tuple[Action, ...] = ()
    bundle_evaluation: Candidate | None = None
    marginals: tuple[float, ...] = ()
    decision: Literal["recommend", "no_change", "abstain"] = "abstain"
    reasons = state.issues
    if request.unit_id and not any(u.id == request.unit_id for u in state.units):
        reasons = (*reasons, "selected_unit_missing")
    warnings = state.warnings
    if request.preparation is not None:
        warnings = (*warnings, "synthetic_learned_preparation_requires_real_validation")
    service_status: Literal[
        "not_assessed", "served_in_all_sampled_scenarios", "unserved_in_some_sampled_scenarios"
    ] = "not_assessed"
    if not reasons:
        actions, truncated = enumerate_actions(
            state, request.max_candidates, request.horizon_minutes
        )
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
            if request.max_bundle > 1 and (state.schedules or selected.kind != "no_op"):
                bundle, bundle_evaluation, marginals = _bundle(
                    state, request, best, baseline, candidates
                )
            if bundle_evaluation:
                selected = bundle[0]
                service_status = (
                    "unserved_in_some_sampled_scenarios"
                    if bundle_evaluation.scenarios_with_unserved_demand
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
    windows = []
    if decision != "abstain":
        for minutes in sorted(
            {m for m in (720, 1440, 4320, request.horizon_minutes) if m <= request.horizon_minutes}
        ):
            if minutes == request.horizon_minutes:
                before = baseline.candidate
                after = bundle_evaluation or best
            else:
                clipped = request.model_copy(update={"horizon_minutes": minutes})
                before = evaluate(
                    state, no_op, clipped, multiday=request.horizon_minutes > 1440
                ).candidate
                after = evaluate(
                    state, bundle or (selected,), clipped, multiday=request.horizon_minutes > 1440
                ).candidate
            windows.append(
                PlanWindow(
                    unserved_scenarios=after.scenarios_with_unserved_demand,
                    change_ratio=(
                        after.mean_waiting_patient_minutes / before.mean_waiting_patient_minutes - 1
                    )
                    if before.mean_waiting_patient_minutes
                    else None,
                    minutes=minutes,
                    baseline_wait=before.mean_waiting_patient_minutes,
                    selected_wait=after.mean_waiting_patient_minutes,
                    saved_wait=before.mean_waiting_patient_minutes
                    - after.mean_waiting_patient_minutes,
                    until=state.at + timedelta(minutes=minutes),
                )
            )
    return Plan(
        unit_id=request.unit_id or (state.units[0].id if len(state.units) == 1 else None),
        windows=tuple(windows),
        horizons=horizons,
        action_timing=tuple(timing(state, a) for a in bundle or (selected,) if a.kind != "no_op"),
        requested_horizon_minutes=requested,
        schema_version="HYBRID_UNIT_PLAN_1"
        if unified
        else "HYBRID_PLAN_5"
        if request.preparation is not None
        and request.preparation.schema_version == "PREPARATION_FORECAST_2"
        else "HYBRID_PLAN_4",
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
        preparation=request.preparation,
        seed=request.seed,
        scenarios=request.scenarios,
        horizon_minutes=request.horizon_minutes,
        tail_weight=request.tail_weight,
        bundle=bundle,
        bundle_evaluation=bundle_evaluation,
        bundle_marginal_minutes=marginals,
        discharge_readiness=readiness(state),
        service_status=service_status,
    )
