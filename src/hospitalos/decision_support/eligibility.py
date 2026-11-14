"""Public admissibility rules, reused at candidate generation AND at review (revalidation).

An automatic discharge coordination is only proposed for a medical authorisation that is
known at decision time. The system never decides a discharge or a prolongation.
"""

from __future__ import annotations

from .contracts import PublicSnapshot, StayState


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


def revalidate_discharge(snapshot: PublicSnapshot, stay_id: str) -> tuple[str, ...]:
    """Recheck an auto/validated discharge against a CURRENT snapshot (T05, T27)."""
    current = stay(snapshot, stay_id)
    if current is None:
        return (f"stay_absent:{stay_id}",)
    return tuple(f"{stay_id}:{r}" for r in discharge_blockers(current))
