"""Expose blockers without presenting a model forecast as medical authorization."""

from __future__ import annotations

from typing import Literal

from hospitalos.operational.contract import Closed

from .models import State, discharge_blockers


class DischargeReadiness(Closed):
    patient_id: str
    stage: Literal[
        "medical_not_confirmed", "logistics_blocked", "transport_to_request", "ready_for_simulation"
    ]
    blockers: tuple[str, ...]


def readiness(state: State) -> tuple[DischargeReadiness, ...]:
    result = []
    for patient in sorted(state.patients, key=lambda p: p.id):
        if patient.status != "admitted":
            continue
        blockers = (*state.issues, *discharge_blockers(state, patient))
        stage: Literal[
            "medical_not_confirmed",
            "logistics_blocked",
            "transport_to_request",
            "ready_for_simulation",
        ]
        if "medical_authorization_not_confirmed" in blockers:
            stage = "medical_not_confirmed"
        elif blockers == ("transport_not_requested",):
            d = next(d for d in state.discharges if d.id == patient.id)
            stage = (
                "transport_to_request" if d.transport_requested is False else "logistics_blocked"
            )
        elif blockers:
            stage = "logistics_blocked"
        else:
            stage = "ready_for_simulation"
        result.append(DischargeReadiness(patient_id=patient.id, stage=stage, blockers=blockers))
    return tuple(result)
