"""Versioned source-document hypotheses; no future course or physical effects.

The legacy variants retain their privileged assumptions. Alternative mechanisms
only use current staff findings and requests already emitted at the source.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from .config import HospitalConfig

ForecastVariant = Literal["admission_prior_v1", "milestones_v1"]
DOM, SMR, EHPAD, TRANSFER = 0, 1, 2, 4
DESTINATIONS = {DOM: "domicile", SMR: "SMR", EHPAD: "EHPAD", TRANSFER: "transfert"}


@dataclass(frozen=True)
class StaffSnapshot:
    """Allowlist for alternative forecasts; all clinical findings are current."""

    admitted_h: int
    dependence: int
    age75: bool
    oxygen: bool
    blocked: bool
    medically_ready: bool
    home_help_pending: bool
    declared_destination: int
    downstream_confirmed: bool


def forecast_day(
    evidence: StaffSnapshot, hour: int, variant: ForecastVariant, uncertainty: float
) -> int:
    """Calendar day from admission prior or current milestones, never an outcome."""
    if uncertainty <= 0 or not math.isfinite(uncertainty):
        raise ValueError("Forecast uncertainty must be finite and positive")
    if evidence.admitted_h > hour:
        raise ValueError("Forecast cannot precede admission")
    waiting_days = {DOM: 0.5, SMR: 3.0, EHPAD: 7.0, TRANSFER: 1.0}[evidence.declared_destination]
    if evidence.downstream_confirmed and evidence.declared_destination in (SMR, EHPAD):
        waiting_days = 0.5
    if variant == "admission_prior_v1":
        typical_days = 2 + 1.5 * evidence.dependence + evidence.age75 + evidence.oxygen
        expected = evidence.admitted_h + 24 * (typical_days + waiting_days) * uncertainty
        floor = hour + (24 if not evidence.medically_ready or evidence.blocked else 12)
        return int(max(floor, expected) // 24)
    if variant != "milestones_v1":
        raise ValueError("Unknown forecast mechanism")
    clinical_days = (
        0.5
        if evidence.medically_ready and not evidence.blocked
        else 1 + 0.8 * evidence.dependence + evidence.oxygen + 1.5 * evidence.blocked
    )
    remaining = max(clinical_days, 2.0 if evidence.home_help_pending else 0.0) + waiting_days
    return int((hour + 24 * remaining * uncertainty) // 24)


@dataclass
class Request:
    requested_h: int
    destination: int
    sequence: int
    due_h: int
    confirmed: bool = False


class DocumentaryMechanisms:
    def __init__(self, config: HospitalConfig):
        self.config = config.documentary
        self.seed = config.seed
        self.review_capacity = max(1, len(config.units) // 2)
        self.requests: dict[int, Request] = {}
        self.sequences: dict[int, int] = {}
        self.review_hour = -1
        self.review_selected: set[int] = set()

    def random(self, *key: str | int) -> np.random.Generator:
        encoded = json.dumps([self.seed, "documentary_v1", *key]).encode()
        return np.random.Generator(
            np.random.PCG64(int.from_bytes(hashlib.sha256(encoded).digest()[:16], "big"))
        )

    def destination(self, pid: int, old: int, declared: int, hour: int) -> None:
        if self.config.downstream_confirmation == "v041":
            return
        if declared not in (SMR, EHPAD):
            self.requests.pop(pid, None)
        elif old != declared or pid not in self.requests:
            seq = self.sequences.get(pid, 0) + 1
            self.sequences[pid] = seq
            random = self.random("request_delay", pid, seq)
            delay = math.ceil(random.lognormal(math.log(36 if declared == SMR else 72), 0.55))
            self.requests[pid] = Request(hour, declared, seq, hour + max(1, delay))

    def confirm(self, sim: Any, state: Any, patient: Any, hour: int, unit: int, log: Any) -> bool:
        """Called only for patients currently medically ready and not blocked.

        True means this variant handles the hook, even if it emits no message.
        Confirmations describe administrative source messages, not a physical bed offer.
        """
        variant = self.config.downstream_confirmation
        if variant == "v041":
            return False
        request = self.requests.get(patient.pid)
        if (
            request is None
            or request.confirmed
            or not sim.x.ouvre[hour // 24]
            or patient.ready_h > hour
            or sim.bloque(patient)
        ):
            return True
        if variant == "request_delay_v1":
            if hour < request.due_h or not 9 <= hour % 24 < 17:
                return True
        else:
            if hour % 24 != 14:
                return True
            if self.review_hour != hour:
                # Current readiness only; no future readiness, departure or queue schedule.
                eligible = [
                    (r.requested_h, pid)
                    for pid, r in self.requests.items()
                    if not r.confirmed
                    and hour - r.requested_h >= 24
                    and (p := state.patients.get(pid)) is not None
                    and p.ready_h <= hour
                    and not sim.bloque(p)
                ]
                self.review_selected = {pid for _, pid in sorted(eligible)[: self.review_capacity]}
                self.review_hour = hour
            if patient.pid not in self.review_selected:
                return True
        request.confirmed = True
        patient.conf = True
        log.event(
            hour,
            "PLACE_AVAL_CONFIRMEE",
            unit,
            patient.pid,
            type_aval=DESTINATIONS[request.destination],
        )
        return True

    def staff(self, sim: Any, state: Any, hour: int, log: Any) -> bool:
        variant = self.config.staff_forecasts
        if variant == "v041":
            return False
        for unit in range(sim.U):
            for p in sorted(state.occ[unit].values(), key=lambda p: p.pid):
                if hour - p.admit_h < 12:
                    continue
                # The staff can assess readiness now, but cannot see when it will occur.
                ready = p.ready_h <= hour and not sim.bloque(p)
                random = self.random("staff_review", p.pid, hour // 24)
                dep = int(sim.p_dep[p.pid])
                if not p.info0:
                    p.info0 = True
                    p.dsp_jamais = self.random("staff_missing", p.pid).random() < 0.30
                    probabilities = (
                        [0.35, 0.35, 0.25, 0.05] if dep >= 3 else [0.75, 0.18, 0.02, 0.05]
                    )
                    destination = int(random.choice([DOM, SMR, EHPAD, TRANSFER], p=probabilities))
                    sim._declarer_destination(p, destination, hour, unit, log)
                elif ready and random.random() < 0.15:
                    # A current functional assessment can revise the requested orientation.
                    destination = EHPAD if dep == 4 else SMR if dep == 3 else DOM
                    if p.dest_decl != destination:
                        sim._declarer_destination(p, destination, hour, unit, log)
                if p.dsp_jamais:
                    continue
                expired = p.dsp <= hour // 24
                revision_probability = 0.25 if variant == "admission_prior_v1" else 0.60
                if p.dsp >= 0 and not expired and random.random() >= revision_probability:
                    continue
                request = self.requests.get(p.pid)
                confirmed = request.confirmed if request else bool(p.conf and p.aval_dem)
                evidence = StaffSnapshot(
                    admitted_h=p.admit_h,
                    dependence=dep,
                    age75=bool(sim.p_age[p.pid] >= 75),
                    oxygen=bool(sim.p_oxy[p.pid]),
                    blocked=bool(sim.bloque(p)),
                    medically_ready=ready,
                    home_help_pending=bool(p.aide_h > hour),
                    declared_destination=p.dest_decl,
                    downstream_confirmed=confirmed,
                )
                period = 0 if variant == "admission_prior_v1" else hour // 24
                uncertainty = float(
                    self.random("forecast", p.pid, variant, period).lognormal(-0.1, 0.25)
                )
                new = forecast_day(evidence, hour, variant, uncertainty)
                if new != p.dsp:
                    p.dsp, p.dsp_n = new, p.dsp_n + 1
                    log.event(
                        hour,
                        "DATE_SORTIE_PREVISIONNELLE",
                        unit,
                        p.pid,
                        date_prevue=sim.x.date_iso(new),
                        revision=p.dsp_n - 1,
                    )
        return True


def documentary_assumptions(config: HospitalConfig) -> list[str]:
    result = [
        "Charge is a noisy synthetic baseline proxy, not SIIPS or hourly delivered care.",
        (
            "Legacy staff plans/orientations use latent course and destination."
            if config.documentary.staff_forecasts == "v041"
            else "Alternative staff plans/orientations use current findings, not future course."
        ),
        (
            "Legacy downstream confirmations use an 18h threshold before scheduled departure."
            if config.documentary.downstream_confirmation == "v041"
            else "Alternative confirmations use requests/current readiness, not bed allocation."
        ),
        "Documentary mechanisms do not change physical departure; mismatches are possible.",
        "Uncalibrated engineering hypotheses; development inspection is not blind evaluation.",
    ]
    if config.smr.mode == "finite_v1":
        result.extend(
            [
                "Finite SMR overrides SMR messages: need disclosed at readiness, confirmation "
                "only on reservation; cancellations/expiry release it.",
                "Provisional non-SMR orientation may be revised at readiness; physical SMR "
                "request is separate from the documentary-delay machinery.",
                "New SMR_* events contain current transitions, no future release time. "
                "They remain in simulation truth; common learning inputs are unchanged.",
            ]
        )
    return result
