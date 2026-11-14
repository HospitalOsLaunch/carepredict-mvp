"""P5 evaluation adapter (P5-PROTO-2 § 5.2). Distinct from, and does not modify, the v6 engine.

Given (public snapshot, chosen plan, private realisation), it removes from the EVALUATION COPY
of the plan's decisions the reinforcement options whose realised presence is 0, then runs the
unchanged v6 simulation under the private truth (``simulate`` + ``TruthProvider``) and the
independent invariant checker. The planner never receives the realisation. Open loop at
``as_of``: an absent offer adds 0 staff; no replacement, no replanning.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from hospitalos.decision_support.contracts import Plan, PublicSnapshot, ReinforcementOption
from hospitalos.decision_support.reference_forecaster import (
    Decisions,
    TruthProvider,
    check_invariants,
    decisions_from_plan,
    simulate,
)

from .generator import offer_key_of
from .truth import Realisation

HORIZON_HOURS = 24


def offer_key(option: ReinforcementOption) -> str:
    return offer_key_of(option.source, option.lending_unit, option.skill, option.start, option.end)


@dataclass(frozen=True)
class Outcome:
    U: int  # uncovered care staff-minutes (OBJ-LEX-1 tier 1), realised
    planned_reinforcement_hours: int
    realised_reinforcement_hours: int
    interventions: int
    waiting_patient_hours: int
    beds_returned: int
    lent_hours_realised: int
    violations: tuple[str, ...]


def evaluation_decisions(
    snapshot: PublicSnapshot, plan: Plan, presence: Mapping[str, int]
) -> tuple[Decisions, tuple[ReinforcementOption, ...]]:
    d = decisions_from_plan(plan, snapshot, snapshot.as_of)
    kept = tuple(o for o in d.reinforcements if presence[offer_key(o)] == 1)
    return Decisions(d.coordinated, d.locked_discharges, d.extensions, kept), kept


def outcome(
    snapshot: PublicSnapshot, plan: Plan, real: Realisation, profile: Mapping[str, Any]
) -> Outcome:
    decisions, kept = evaluation_decisions(snapshot, plan, real.presence)
    start = snapshot.as_of
    run = simulate(snapshot, profile, start, HORIZON_HOURS, decisions, TruthProvider(real.truth))
    violations = tuple(sorted(set(run.violations) | set(check_invariants(snapshot, start, run, False))))
    return Outcome(
        U=int(sum(run.uncovered_unit) + sum(run.uncovered_waiting)),
        planned_reinforcement_hours=plan.reinforcement_hours,
        realised_reinforcement_hours=sum(o.hours for o in kept),
        interventions=plan.interventions,
        waiting_patient_hours=int(sum(run.waiting)),
        beds_returned=int(run.beds_returned),
        lent_hours_realised=sum(o.hours for o in kept if o.source == "shared_unit"),
        violations=violations,
    )
