"""Finite, explicit universe of plans built from the public snapshot only (P3).

The habitual practice (no action) is always the first plan. Coordinations and reinforcement
options are combined directly (their joint effect is simulated, never summed). If the
universe exceeds the search bound, the evaluated prefix is recorded with complete=False and
no optimum is claimed (T24).
"""

from __future__ import annotations

import hashlib
import itertools
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from .clock import display, local_hour
from .contracts import ActionSpec, Plan, PublicSnapshot, ReinforcementOption, SearchReport
from .eligibility import discharge_blockers
from .resources import lending_violations, option_admissibility


def _key(*parts: object) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:24]


def coordination_action(
    snapshot: PublicSnapshot, stay_id: str, target: datetime, valid_until: datetime
) -> ActionSpec:
    stay = next(s for s in snapshot.stays if s.stay_id == stay_id)
    needs = stay.transport_need in {"seated", "stretcher"}
    return ActionSpec(
        action_id=f"coord:{stay_id}:{target.strftime('%Y%m%dT%H%MZ')}",
        type="coordinate_discharge",
        target=stay_id,
        window_start=target,
        window_end=target + timedelta(hours=1),
        preconditions=(
            "medical_authorization_observed_at_decision",
            "revalidate_authorization_before_approval",
            *(("transport_requested_now_lead_time_respected",) if needs else ()),
            "cleaning_only_after_effective_departure",
        ),
        resources=(*(("transport_team",) if needs else ()), "cleaning_team", "IDE:discharge_task"),
        validator="cadre_de_sante",
        idempotency_key=_key(snapshot.unit.unit_id, "coordinate_discharge", stay_id, target),
        valid_until=valid_until,
        origin="auto",
        basis="observed_authorization",
    )


def reinforcement_action(
    snapshot: PublicSnapshot,
    option: ReinforcementOption,
    valid_until: datetime,
    origin: str = "auto",
) -> ActionSpec:
    return ActionSpec(
        action_id=f"renfort:{option.option_id}",
        type="reinforcement",
        target=option.option_id,
        window_start=option.start,
        window_end=option.end,
        preconditions=(
            f"skill:{option.skill}",
            f"confirmation:{option.confirmation}",
            *((f"lending_unit:{option.lending_unit}",) if option.lending_unit else ()),
        ),
        resources=(f"{option.skill}:{display(option.start)}-{display(option.end)}",),
        reinforcement_hours=option.hours,
        interventions=1,
        validator="cadre_de_sante",
        idempotency_key=_key(snapshot.unit.unit_id, "reinforcement", option.option_id),
        valid_until=valid_until,
        origin=origin,  # type: ignore[arg-type]
        basis="resource_option",
        conditional=option.confirmation != "confirmed",
    )


def plan_id(snapshot: PublicSnapshot, mode: str, actions: tuple[ActionSpec, ...]) -> str:
    return "plan-" + _key(snapshot.fingerprint, mode, *sorted(a.action_id for a in actions))[:16]


def make_plan(
    snapshot: PublicSnapshot,
    mode: str,
    actions: tuple[ActionSpec, ...],
    label: str,
    locked: tuple[str, ...] = (),
) -> Plan:
    return Plan(
        plan_id=plan_id(snapshot, mode, actions),
        snapshot_id=snapshot.snapshot_id,
        snapshot_fingerprint=snapshot.fingerprint,
        mode=mode,  # type: ignore[arg-type]
        label=label,
        actions=actions,
        locked_action_ids=locked,
        assumptions=("synthetic_unit", "public_distributions_are_declared_hypotheses"),
    )


def enumerate_plans(
    snapshot: PublicSnapshot,
    profile: Mapping[str, Any],
    start: datetime,
    end: datetime,
    valid_until: datetime,
    mode: str = "auto",
    locked_actions: tuple[ActionSpec, ...] = (),
    excluded_stays: frozenset[str] = frozenset(),
    excluded_options: frozenset[str] = frozenset(),
    limit: int | None = None,
) -> tuple[list[Plan], SearchReport]:
    limits = profile["limits"]
    limit = limit or int(limits["max_plans"])
    rejected: dict[str, str] = {}
    targets_local = profile["coordination_target_local_hours"]
    per_stay: dict[str, list[ActionSpec]] = {}
    for stay in snapshot.stays:
        if stay.stay_id in excluded_stays:
            rejected[stay.stay_id] = "locked_by_user"
            continue
        blockers = discharge_blockers(stay)
        if blockers:
            rejected[stay.stay_id] = ",".join(blockers)
            continue
        options = []
        h = start
        while h < end:
            if local_hour(h) in targets_local:
                assert stay.ready_earliest is not None
                early_enough = stay.planned_departure is None or h < stay.planned_departure
                if h >= stay.ready_earliest and early_enough:
                    options.append(coordination_action(snapshot, stay.stay_id, h, valid_until))
            h += timedelta(hours=1)
        if options:
            per_stay[stay.stay_id] = options
        else:
            rejected[stay.stay_id] = "no_target_hour_before_habitual_plan"
    admissible_options = []
    for option in snapshot.reinforcements:
        if option.option_id in excluded_options:
            rejected[option.option_id] = "locked_by_user"
            continue
        ok, reason = option_admissibility(option, start, end)
        if ok:
            admissible_options.append(option)
        else:
            rejected[option.option_id] = reason
    coord_sets: list[tuple[ActionSpec, ...]] = [()]
    stays = sorted(per_stay)
    for n in range(1, int(limits["max_coordinations_per_plan"]) + 1):
        for chosen in itertools.combinations(stays, n):
            coord_sets += list(itertools.product(*(per_stay[s] for s in chosen)))
    by_id = {o.option_id: o for o in snapshot.reinforcements}
    locked_options = [by_id[a.target] for a in locked_actions if a.type == "reinforcement"]
    reinf_sets: list[tuple[ActionSpec, ...]] = [()]
    for n in range(1, int(limits["max_reinforcement_options_per_plan"]) + 1):
        for chosen in itertools.combinations(admissible_options, n):
            # F02: options allowed alone may be forbidden together (same lender, skill, hour).
            cumulative = lending_violations([*locked_options, *chosen], snapshot.reinforcements)
            if cumulative:
                rejected["+".join(o.option_id for o in chosen)] = cumulative[0]
                continue
            reinf_sets.append(tuple(reinforcement_action(snapshot, o, valid_until) for o in chosen))
    combos = [c + r for c in coord_sets for r in reinf_sets]
    combos.sort(
        key=lambda acts: (
            len(acts),
            sum(a.reinforcement_hours for a in acts),
            tuple(a.action_id for a in acts),
        )
    )
    locked_ids = tuple(a.action_id for a in locked_actions)
    plans = [
        make_plan(
            snapshot,
            mode,
            locked_actions + acts,
            (
                "pratique habituelle"
                if not acts and not locked_actions
                else "scénario verrouillé seul"
                if not acts
                else " + ".join(a.action_id for a in acts)
            ),
            locked_ids,
        )
        for acts in combos[:limit]
    ]
    report = SearchReport(
        enumerated=len(combos),
        evaluated=len(plans),
        limit=limit,
        complete=len(combos) <= limit,
        filter_rules=(
            "auto discharge coordination only with observed medical authorization and no open obstacle",  # noqa: E501
            "target hours from profile, not before readiness estimate, before any planned departure",  # noqa: E501
            "reinforcement options: known confirmation status and external commitment respected",
            "reinforcement combinations: cumulative loans per lender, skill and hour respected",
            f"at most {limits['max_coordinations_per_plan']} coordinations and "
            f"{limits['max_reinforcement_options_per_plan']} reinforcement options per plan",
            "ordering: fewer actions, fewer reinforcement hours, then identifiers; "
            "prefix kept when the universe exceeds the bound",
        ),
        rejected=rejected,
    )
    return plans, report
