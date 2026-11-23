"""Fictional two-unit episodes and a separate, hand-calculable outcome oracle.

These are fresh decision episodes, not the continuous evolution of one hospital.
Hidden preparation times and unannounced disruptions never enter PlanRequest.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from .innovations import uniform
from .models import Action, Bed, Discharge, Fact, FactEvent, Patient, ResourcePool, Unit
from .planning import PlanRequest
from .preparation import EDGES, features_at
from .scenarios import FutureTape, ResourceChange
from .scoring import ResourcePressure, Score, score
from .simulation import Assumptions, simulate
from .survival import PreparationRecord

Stream = Literal["stable", "reorganization", "operational_shock", "development"]
UNITS = ("medicine", "medicine-2")
CHANGE_INDEX = 16


@dataclass(frozen=True)
class HiddenOutcome:
    completion: tuple[tuple[str, int | None], ...]
    feedback: tuple[PreparationRecord, ...]
    future: FutureTape
    shock: bool


@dataclass(frozen=True)
class DecisionEpisode:
    request: PlanRequest
    hidden: HiddenOutcome


def episode(
    at: datetime, seed: int, index: int, stream: Stream, *, scenarios: int = 32
) -> DecisionEpisode:
    context = random.Random(seed * 100003 + index)
    facts: list[Fact] = []
    prefix = f"decision-{seed}-{index}"
    for unit_index, unit_id in enumerate(UNITS):
        high = context.choice((False, True))
        waiting = context.choice((1, 2))
        outgoing = f"{prefix}:out-{unit_index}"
        background = f"{prefix}:resident-{unit_index}"
        bed = f"bed-{unit_index}-0"
        facts.extend(
            (
                Unit(id=unit_id, staffed_beds=2, cleaning_teams=1),
                Bed(id=bed, unit_id=unit_id, state="occupied", occupant=outgoing),
                Patient(
                    id=outgoing,
                    status="admitted",
                    compatible_units=(unit_id,),
                    bed_id=bed,
                    waiting_since=at - timedelta(days=1),
                    medically_cleared=True,
                    downstream_confirmed=True,
                ),
                Discharge(
                    id=outgoing,
                    documents_ready=True,
                    escort_required=False,
                    transport_required=True,
                    transport_requested=False,
                    transport_pool_id="transport",
                    downstream_required=True,
                    downstream_pool_id="downstream",
                ),
            )
        )
        facts.append(
            Bed(
                id=f"bed-{unit_index}-1",
                unit_id=unit_id,
                state="occupied" if high else "closed",
                occupant=background if high else None,
            )
        )
        if high:
            facts.append(
                Patient(
                    id=background,
                    status="admitted",
                    compatible_units=(unit_id,),
                    bed_id=f"bed-{unit_index}-1",
                    waiting_since=at - timedelta(days=2),
                    medically_cleared=False,
                )
            )
        facts.extend(
            Patient(
                id=f"{prefix}:wait-{unit_index}-{j}",
                status="waiting",
                compatible_units=(unit_id,),
                waiting_since=at - timedelta(minutes=30),
            )
            for j in range(waiting)
        )
    facts.extend(
        (
            ResourcePool(id="transport", resource="transport", unit_ids=UNITS, available=1),
            ResourcePool(id="downstream", resource="downstream", unit_ids=UNITS, available=1),
        )
    )
    request = PlanRequest(
        hospital_id="fictional-hospital",
        at=at,
        expected_entities=tuple(f"{f.kind}:{f.id}" for f in facts),
        events=tuple(
            FactEvent(
                hospital_id="fictional-hospital",
                event_id=f"{prefix}:{f.kind}:{f.id}",
                source="fictional_decision_feed",
                event_time=at,
                available_at=at,
                fact=f,
            )
            for f in facts
        ),
        horizon_minutes=360,
        scenarios=scenarios,
        seed=seed * 100003 + index,
        assumptions=Assumptions(
            departure_minutes=(30,),
            transport_minutes=(45,),
            transport_return_minutes=(30,),
            cleaning_minutes=(30,),
            load_multipliers=(1,),
        ),
    )
    state = request.state()
    if state.issues:
        raise ValueError(f"Invalid fictional state: {state.issues}")
    times, feedback = [], []
    for patient in sorted(state.discharges, key=lambda d: d.id):
        f = features_at(state, patient.id)
        coefficient, intercept = -2.0, 0.0
        if stream == "development":
            coefficient = (-2.0, -1.0, 0.0)[index % 3]
            intercept = (0.0, -0.4, 0.3)[index % 3]
        elif index >= CHANGE_INDEX and stream == "reorganization":
            coefficient = 1.5
            intercept = 0.7 * math.cos(2 * math.pi * at.hour / 24) - 0.5 * f.waiting_per_staffed_bed
        elif index >= CHANGE_INDEX and stream == "operational_shock":
            coefficient = -0.2
            intercept = -0.7 - (0.5 if at.hour < 8 else 0)
        value = uniform(seed, index, "actual_preparation", patient.id)
        survival, cumulative = 1.0, 0.0
        completion = None
        for j, edge in enumerate(EDGES):
            logit = (
                -0.8
                + 0.18 * j
                + coefficient * (f.occupied_per_staffed_bed - 0.8)
                - 0.7 * f.waiting_per_staffed_bed
                + 0.3 * math.sin(2 * math.pi * at.hour / 24)
                + intercept
            )
            hazard = 1 / (1 + math.exp(-logit))
            cumulative += survival * hazard
            survival *= 1 - hazard
            if value < cumulative:
                completion = edge
                break
        censor = (180, 300, 1440, 1440)[int(uniform(seed, index, "followup", patient.id) * 4)]
        feedback.append(
            PreparationRecord(
                episode_id=patient.id,
                patient_id=patient.id,
                hospital_id=state.hospital_id,
                unit_id=next(b.unit_id for b in state.beds if b.occupant == patient.id),
                origin=at,
                features_available_at=at,
                features=f,
                followed_minutes=min(completion if completion is not None else 1441, censor),
                event_observed=completion is not None and completion <= censor,
                label_available_at=at + timedelta(hours=24),
            )
        )
        times.append((patient.id, completion))
    shock = stream == "operational_shock" and index >= CHANGE_INDEX
    changes: list[ResourceChange] = []
    if shock:
        changes.extend(
            (
                ResourceChange(
                    id="actual-transport-off",
                    minute=60,
                    resource="transport",
                    target_id="transport",
                    capacity=0,
                ),
                ResourceChange(
                    id="actual-transport-on",
                    minute=150,
                    resource="transport",
                    target_id="transport",
                    capacity=1,
                ),
            )
        )
        for unit in UNITS:
            changes.extend(
                (
                    ResourceChange(
                        id=f"actual-staff-off:{unit}",
                        minute=90,
                        resource="staffed_beds",
                        target_id=unit,
                        capacity=1,
                    ),
                    ResourceChange(
                        id=f"actual-staff-on:{unit}",
                        minute=210,
                        resource="staffed_beds",
                        target_id=unit,
                        capacity=2,
                    ),
                )
            )
    return DecisionEpisode(
        request, HiddenOutcome(tuple(times), tuple(feedback), FutureTape(at, tuple(changes)), shock)
    )


def hand_oracle(case: DecisionEpisode, action: Action) -> Score:
    """Independent arithmetic for this fixture only; never calls simulate or score."""
    state = case.request.state()
    horizon = case.request.horizon_minutes
    if horizon != 360 or action.kind not in {"no_op", "request_transport"}:
        raise ValueError("Oracle is limited to this six-hour fixture/action catalogue")
    waiting = sum(p.status == "waiting" for p in state.patients)
    unit_id = None
    depart = admit = return_at = start = math.inf
    if action.kind == "request_transport":
        ready = dict(case.hidden.completion)[action.patient_id or ""]
        bed = next(b for b in state.beds if b.id == action.bed_id)
        unit_id = bed.unit_id
        if ready is not None:
            start = 150 if case.hidden.shock and 60 <= ready < 150 else ready
            depart = start + 45
            return_at = depart + 30
            admit = depart + 30
            background = (
                sum(b.unit_id == unit_id and b.occupant is not None for b in state.beds) - 1
            )
            if case.hidden.shock and background >= 1 and 90 <= admit < 210:
                admit = 210
    admitted = int(admit <= horizon)
    staffed = 0.0
    for unit in state.units:
        initial = sum(b.unit_id == unit.id and b.occupant is not None for b in state.beds)
        cuts = sorted(
            {0.0, float(horizon), *(x for x in (90.0, 210.0, depart, admit) if 0 < x < horizon)}
        )
        for left, right in zip(cuts[:-1], cuts[1:], strict=True):
            occupancy = (
                initial
                - int(unit.id == unit_id and left >= depart)
                + int(unit.id == unit_id and left >= admit)
            )
            capacity = 1 if case.hidden.shock and 90 <= left < 210 else 2
            staffed += (right - left) * max(0, occupancy - capacity)
    transport = (
        max(0, min(return_at, 150, horizon) - max(start, 60))
        if case.hidden.shock and start < 60
        else 0
    )
    return Score(
        waiting_patient_minutes=int(waiting * horizon - (horizon - admit if admitted else 0)),
        admitted=admitted,
        waiting_at_end=waiting - admitted,
        violations=(),
        pressure=ResourcePressure(
            staffed_patient_minutes=int(staffed), transport_team_minutes=int(transport)
        ),
    )


def actual_score(case: DecisionEpisode, action: Action) -> Score:
    ready = dict(case.hidden.completion).get(action.patient_id or "")
    # Only one transport request is permitted. Other patients have no scheduled departure.
    assumptions = case.request.assumptions.model_copy(
        update={"departure_minutes": (ready if ready is not None else 1440,)}
    )
    trace = simulate(
        case.request.state(),
        action,
        assumptions,
        seed=case.request.seed,
        scenario=0,
        horizon_minutes=360,
        future=case.hidden.future,
    )
    result = score(case.request.state(), trace, expected_future=case.hidden.future)
    expected = hand_oracle(case, action)
    if result != expected:
        raise AssertionError(f"Independent decision oracle disagreement: {result} != {expected}")
    return result
