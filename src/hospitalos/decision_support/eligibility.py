"""Public admissibility rules, shared by candidate generation, manual locks and review.

An automatic discharge coordination is only proposed for a medical authorisation that is
known at decision time. The system never decides a discharge or a prolongation. A manual lock
keeps its time exactly (never moved), but it must satisfy the same preconditions as an
automatic action to be approvable; otherwise it is simulated as a hypothesis (F01).
"""

from __future__ import annotations

from datetime import datetime

from .contracts import Plan, PublicSnapshot, StayState
from .resources import hour_index, hour_index_ceil, lending_violations, option_admissibility

DISCHARGE_TYPES = {"coordinate_discharge", "locked_discharge", "locked_extension"}


def discharge_blockers(stay: StayState) -> tuple[str, ...]:
    reasons: list[str] = []
    if stay.medical_authorization != "authorized":
        reasons.append(f"medical_authorization_{stay.medical_authorization}")
    if stay.destination == "unknown":
        reasons.append("destination_unknown")
    if stay.transport_need == "unknown":
        reasons.append("transport_need_unknown")
    if stay.transport_need in {"seated", "stretcher"} and stay.transport_lead is None:
        reasons.append("transport_lead_unknown")
    if stay.ready_earliest is None or stay.ready_delay is None:
        reasons.append("readiness_estimate_unknown")
    reasons.extend(f"obstacle:{code}" for code in stay.obstacles)
    return tuple(reasons)


def eligible_for_auto_discharge(stay: StayState) -> bool:
    return not discharge_blockers(stay)


def stay(snapshot: PublicSnapshot, stay_id: str) -> StayState | None:
    return next((s for s in snapshot.stays if s.stay_id == stay_id), None)


def lock_timing_issues(stay: StayState, start: datetime, at: datetime) -> tuple[str, ...]:
    """Public timing preconditions of a departure fixed at ``at`` (hour index on the grid).

    'certain': contradicted in every forecast scenario; 'possible': in some of them.
    """
    idx = hour_index(start, at)
    issues: list[str] = []
    if stay.ready_earliest is not None and stay.ready_delay is not None:
        earliest = max(0, hour_index_ceil(start, stay.ready_earliest))
        if idx < earliest + min(stay.ready_delay.support):
            issues.append("lock_before_readiness_estimate:certain")
        elif idx < earliest + max(stay.ready_delay.support):
            issues.append("lock_before_readiness_estimate:possible")
    if stay.transport_need in {"seated", "stretcher"} and stay.transport_lead is not None:
        if idx < min(stay.transport_lead.support):
            issues.append("lock_before_transport_lead:certain")
        elif idx < max(stay.transport_lead.support):
            issues.append("lock_before_transport_lead:possible")
    return tuple(issues)


def lock_precondition_issues(stay: StayState, start: datetime, at: datetime) -> tuple[str, ...]:
    """Everything that prevents a validated lock from being approvable as an executable plan."""
    return discharge_blockers(stay) + lock_timing_issues(stay, start, at)


def plan_precondition_errors(snapshot: PublicSnapshot, plan: Plan) -> tuple[str, ...]:
    """Revalidation used at approval time, identical for auto and manual plans (F01)."""
    errors: list[str] = []
    start = snapshot.as_of
    options = {o.option_id: o for o in snapshot.reinforcements}
    chosen = []
    for a in plan.actions:
        if a.type in DISCHARGE_TYPES:
            current = stay(snapshot, a.target)
            if current is None:
                errors.append(f"{a.target}:stay_absent")
                continue
            if a.type == "coordinate_discharge":
                errors += [f"{a.target}:{r}" for r in discharge_blockers(current)]
            elif a.basis == "hypothesis_only":
                errors.append(f"{a.target}:hypothesis_only_not_executable")
            else:
                issues = lock_precondition_issues(current, start, a.window_start)
                errors += [f"{a.target}:{r}" for r in issues]
        elif a.type == "reinforcement":
            option = options.get(a.target)
            if option is None:
                errors.append(f"{a.target}:reinforcement_option_absent")
                continue
            ok, reason = option_admissibility(option, start, plan_end(snapshot, a.window_end))
            if not ok:
                errors.append(f"{a.target}:{reason}")
            chosen.append(option)
    errors += lending_violations(chosen, snapshot.reinforcements)
    return tuple(errors)


def plan_end(snapshot: PublicSnapshot, end: datetime) -> datetime:
    """Horizon end used for option windows at review time (at least the option's own end)."""
    return max(end, snapshot.as_of)


def revalidate_discharge(snapshot: PublicSnapshot, stay_id: str) -> tuple[str, ...]:
    """Recheck an auto/validated discharge against a CURRENT snapshot (T05, T27)."""
    current = stay(snapshot, stay_id)
    if current is None:
        return (f"stay_absent:{stay_id}",)
    return tuple(f"{stay_id}:{r}" for r in discharge_blockers(current))
