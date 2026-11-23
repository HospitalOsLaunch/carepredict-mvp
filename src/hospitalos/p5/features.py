"""features(PublicSnapshot, Plan, P5 public sidecar) — P5-PROTO-2 § 6.2, schema HOSPITALOS_P5_FEATURES_1.

Inputs are public only. Identifiers (stay_id, option_id, request_id, lending_unit) are used to
JOIN plan actions to slots and to compute lender margins; they are never emitted as values nor
hashed into features. Slots are ordered canonically by their public attributes, then by the
plan-link fields; absent slots are all-zero with mask 0; "not applicable" is 0 plus an explicit
indicator; categories are one-hot over a fixed vocabulary (out-of-vocabulary = stop).
B0/B1 are shared by M_agg and M_ent; B2-B4 belong to M_ent only.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from hospitalos.decision_support.clock import PARIS, local_hour
from hospitalos.decision_support.contracts import Distribution, Plan, PublicSnapshot
from hospitalos.decision_support.eligibility import eligible_for_auto_discharge
from hospitalos.decision_support.resources import (
    hour_index,
    lender_capacities,
    option_admissibility,
    staff_per_hour,
    team_capacity,
    touched_hours,
)

from .eval_adapter import offer_key
from .generator import OBSTACLE_VOCAB

SCHEMA = "HOSPITALOS_P5_FEATURES_1"
H = 24
SKILLS = ("IDE", "AS")
BED_STATUS = ("occupied", "clean", "dirty", "cleaning", "closed", "unknown")
AUTH = ("authorized", "not_authorized", "revoked", "unknown")
DEST = ("home", "facility", "unknown")
TRANSPORT = ("none", "seated", "stretcher", "unknown")
SOURCES = ("internal_pool", "interim", "shared_unit")
CONFIRM = ("confirmed", "requested", "not_requested", "unknown")
N_STAY, N_OFFER, N_ADM = 8, 4, 4


B0_LAYOUT = (
    ("beds_by_status", 6), ("n_beds", 1), ("n_oxygen_beds", 1), ("n_stays", 1), ("auth_counts", 4),
    ("n_eligible", 1), ("transport_counts", 4), ("destination_counts", 3), ("obstacle_counts", 3),
    ("planned_departures_by_hour", H), ("care_minutes_IDE_by_hour", H), ("care_minutes_AS_by_hour", H),
    ("staff_IDE_by_hour", H), ("staff_AS_by_hour", H), ("transport_residual_by_hour", H),
    ("cleaning_residual_by_hour", H), ("admissions_expected_by_hour", H), ("n_admissions", 1),
    ("n_admissions_oxygen", 1), ("admission_care_day_sum", 1), ("offers_by_source_confirmation", 6),
    ("n_offers_admissible", 1), ("expected_offer_hours", 1), ("as_of_hour_sincos", 2), ("weekday", 7),
)


def _layout_names(prefix: str, layout: tuple[tuple[str, int], ...]) -> list[str]:
    return [f"{prefix}.{n}.{i}" if k > 1 else f"{prefix}.{n}" for n, k in layout for i in range(k)]


class FeatureError(RuntimeError):
    """Out-of-vocabulary category or slot overflow: stop rule, never truncation."""


def _mean(d: Distribution | None) -> float:
    if d is None:
        return 0.0
    return sum(v * w for v, w in zip(d.support, d.weights, strict=True)) / sum(d.weights)


def _sd(d: Distribution) -> float:
    m = _mean(d)
    var = sum(w * (v - m) ** 2 for v, w in zip(d.support, d.weights, strict=True)) / sum(d.weights)
    return math.sqrt(var)


def _onehot(value: str, vocab: tuple[str, ...], what: str) -> list[float]:
    if value not in vocab:
        raise FeatureError(f"out_of_vocabulary:{what}:{value}")
    return [1.0 if value == v else 0.0 for v in vocab]


def _opt(value: float | None) -> list[float]:
    return [0.0, 0.0] if value is None else [float(value), 1.0]


class SnapshotFeatures:
    """Plan-independent parts computed once per snapshot; ``row(plan)`` adds the plan."""

    def __init__(
        self, snapshot: PublicSnapshot, sidecar: Mapping[str, Mapping[str, Any]], profile: Mapping[str, Any]
    ) -> None:
        self.snap = snapshot
        self.start = snapshot.as_of
        self.sidecar = sidecar
        self.profile = profile
        if len(snapshot.stays) > N_STAY or len(snapshot.reinforcements) > N_OFFER or len(snapshot.admissions) > N_ADM:
            raise FeatureError("slot_overflow")
        day = profile["day_local_hours"]
        self.is_day = [
            day["start"] <= local_hour(self.start + timedelta(hours=h)) < day["end"] for h in range(H)
        ]
        self.b0_names, self.b0 = self._b0()
        if self.b0_names != _layout_names("B0", B0_LAYOUT):
            raise FeatureError("B0 layout drift")
        self.stay_public = {s.stay_id: self._stay_public(s) for s in snapshot.stays}
        self.offer_public = {o.option_id: self._offer_public(o) for o in snapshot.reinforcements}
        self.adm_rows = sorted(self._adm_public(a) for a in snapshot.admissions)

    # ------------------------------------------------------------------ B0
    def _care_hourly(self, care: Any, skill: str) -> list[float]:
        for c in care:
            if c.skill == skill:
                return [float(c.day_minutes_per_hour if d else c.night_minutes_per_hour) for d in self.is_day]
        return [0.0] * H

    def _b0(self) -> tuple[list[str], list[float]]:
        s, names, vals = self.snap, [], []

        def add(name: str, values: list[float]) -> None:
            names.extend(f"B0.{name}.{i}" if len(values) > 1 else f"B0.{name}" for i in range(len(values)))
            vals.extend(values)

        add("beds_by_status", [float(sum(b.status == st for b in s.beds)) for st in BED_STATUS])
        add("n_beds", [float(len(s.beds))])
        add("n_oxygen_beds", [float(sum("oxygen" in b.capabilities for b in s.beds))])
        add("n_stays", [float(len(s.stays))])
        add("auth_counts", [float(sum(x.medical_authorization == a for x in s.stays)) for a in AUTH])
        add("n_eligible", [float(sum(eligible_for_auto_discharge(x) for x in s.stays))])
        add("transport_counts", [float(sum(x.transport_need == t for x in s.stays)) for t in TRANSPORT])
        add("destination_counts", [float(sum(x.destination == d for x in s.stays)) for d in DEST])
        obst = [0.0] * len(OBSTACLE_VOCAB)
        for x in s.stays:
            for code in x.obstacles:
                obst = [a + b for a, b in zip(obst, _onehot(code, OBSTACLE_VOCAB, "obstacle"), strict=True)]
        add("obstacle_counts", obst)
        planned = [0.0] * H
        for x in s.stays:
            if x.planned_departure is not None:
                i = hour_index(self.start, x.planned_departure)
                if 0 <= i < H:
                    planned[i] += 1
        add("planned_departures_by_hour", planned)
        for k in SKILLS:
            care = [0.0] * H
            for x in s.stays:
                care = [a + b for a, b in zip(care, self._care_hourly(x.care, k), strict=True)]
                for t in x.tasks:
                    i = hour_index(self.start, t.start)
                    if t.skill == k and 0 <= i < H:
                        care[i] += t.minutes * t.staff_required
            add(f"care_minutes_{k}_by_hour", care)
        for k in SKILLS:
            sched, _ = staff_per_hour(s, k, self.start, H)
            add(f"staff_{k}_by_hour", [float(v) for v in sched])
        for team in ("transport", "cleaning"):
            cap, _ = team_capacity(s.teams, team, self.start, H)
            add(f"{team}_residual_by_hour", [float(v) for v in cap])
        arrivals = [0.0] * H
        for a in s.admissions:
            i = hour_index(self.start, a.expected_arrival)
            arrivals[min(max(i, 0), H - 1)] += 1
        add("admissions_expected_by_hour", arrivals)
        add("n_admissions", [float(len(s.admissions))])
        add("n_admissions_oxygen", [float(sum("oxygen" in a.requirements for a in s.admissions))])
        add(
            "admission_care_day_sum",
            [float(sum(c.day_minutes_per_hour for a in s.admissions for c in a.care if c.skill == "IDE"))],
        )
        counts = []
        for src in SOURCES:
            for conf in ("confirmed", "requested"):
                counts.append(float(sum(o.source == src and o.confirmation == conf for o in s.reinforcements)))
        add("offers_by_source_confirmation", counts)
        end = self.start + timedelta(hours=H)
        admissible = [o for o in s.reinforcements if option_admissibility(o, self.start, end)[0]]
        add("n_offers_admissible", [float(len(admissible))])
        add("expected_offer_hours", [sum(float(self.sidecar[offer_key(o)]["p_pub"]) * o.hours for o in admissible)])
        lh = local_hour(self.start)
        add("as_of_hour_sincos", [math.sin(2 * math.pi * lh / 24), math.cos(2 * math.pi * lh / 24)])
        wd = self.start.astimezone(PARIS).weekday()
        add("weekday", [1.0 if wd == i else 0.0 for i in range(7)])
        return names, vals

    # ------------------------------------------------------------------ slots (public part)
    def _stay_public(self, x: Any) -> list[float]:
        beds = {b.bed_id: b for b in self.snap.beds}
        bed = beds.get(x.bed_id or "")
        care = [0.0] * 4
        for k in SKILLS:
            for h, v in enumerate(self._care_hourly(x.care, k)):
                care[h // 6] += v
        task_minutes = sum(t.minutes * t.staff_required for t in x.tasks)
        obst = [0.0] * len(OBSTACLE_VOCAB)
        for code in x.obstacles:
            obst = [a + b for a, b in zip(obst, _onehot(code, OBSTACLE_VOCAB, "obstacle"), strict=True)]
        return [
            1.0,
            *_onehot(x.medical_authorization, AUTH, "authorization"),
            *_onehot(x.destination, DEST, "destination"),
            *_onehot(x.transport_need, TRANSPORT, "transport_need"),
            *_opt(_mean(x.transport_lead) if x.transport_lead is not None else None),
            *_opt(hour_index(self.start, x.ready_earliest) if x.ready_earliest is not None else None),
            *_opt(_mean(x.ready_delay) if x.ready_delay is not None else None),
            *_opt(hour_index(self.start, x.planned_departure) if x.planned_departure is not None else None),
            *care,
            float(len(x.tasks)),
            float(task_minutes),
            *obst,
            1.0 if bed is not None and "oxygen" in bed.capabilities else 0.0,
            _mean(bed.cleaning) if bed is not None else 0.0,
            *_onehot(bed.status if bed is not None else "unknown", BED_STATUS, "bed_status"),
        ]

    STAY_PUBLIC_NAMES = (
        ["mask", *[f"auth_{a}" for a in AUTH], *[f"dest_{d}" for d in DEST], *[f"transport_{t}" for t in TRANSPORT],
         "lead_mean", "lead_ind", "ready_idx", "ready_ind", "ready_delay_mean", "ready_delay_ind",
         "planned_idx", "planned_ind", "care_q1", "care_q2", "care_q3", "care_q4", "n_tasks", "task_staff_minutes",
         *[f"obstacle_{o}" for o in OBSTACLE_VOCAB], "bed_oxygen", "bed_cleaning_mean", *[f"bed_{b}" for b in BED_STATUS]]
    )
    STAY_LINK_NAMES = ["targeted", "action_coordinate", "target_idx", "target_ind"]

    def _offer_public(self, o: Any) -> list[float]:
        end = self.start + timedelta(hours=H)
        caps = lender_capacities(self.snap.reinforcements)
        spare: float | None = None
        conflict = 0.0
        if o.source == "shared_unit" and o.lending_unit is not None:
            vals = [caps.get((o.lending_unit, o.skill, h)) for h in touched_hours(o.start, o.end)]
            known = [c.spare for c in vals if c is not None and c.spare is not None]
            spare = float(min(known)) if known and len(known) == len(vals) else None
            conflict = 1.0 if any(c is not None and c.conflicting for c in vals) else 0.0
        return [
            1.0,
            *_onehot(o.source, SOURCES, "source"),
            *_onehot(o.confirmation, CONFIRM, "confirmation"),
            float(hour_index(self.start, o.start)),
            float(hour_index(self.start, o.end)),
            float(o.hours),
            float(self.sidecar[offer_key(o)]["p_pub"]),
            1.0 if option_admissibility(o, self.start, end)[0] else 0.0,
            *_opt(spare),
            conflict,
        ]

    OFFER_PUBLIC_NAMES = (
        ["mask", *[f"source_{s}" for s in SOURCES], *[f"confirmation_{c}" for c in CONFIRM], "start_idx", "end_idx",
         "hours", "p_pub", "admissible", "lender_spare", "lender_spare_ind", "lender_conflict"]
    )
    OFFER_LINK_NAMES = ["selected"]

    def _adm_public(self, a: Any) -> list[float]:
        care = next((c for c in a.care if c.skill == "IDE"), None)
        return [
            1.0,
            float(hour_index(self.start, a.expected_arrival)),
            _mean(a.arrival_delay),
            _sd(a.arrival_delay),
            float(care.day_minutes_per_hour) if care else 0.0,
            float(care.night_minutes_per_hour) if care else 0.0,
            float(a.admission_task_minutes),
            1.0 if "oxygen" in a.requirements else 0.0,
        ]

    ADM_NAMES = ["mask", "arrival_idx", "delay_mean", "delay_sd", "care_day", "care_night", "admission_minutes", "requires_oxygen"]

    # ------------------------------------------------------------------ rows
    def _b1(self, plan: Plan) -> tuple[list[str], list[float]]:
        coord = [a for a in plan.actions if a.type == "coordinate_discharge"]
        reinf = [a for a in plan.actions if a.type == "reinforcement"]
        options = {o.option_id: o for o in self.snap.reinforcements}
        hist = [0.0] * H
        for a in coord:
            hist[hour_index(self.start, a.window_start)] += 1
        staff = [0.0] * H
        expected = 0.0
        for a in reinf:
            o = options[a.target]
            expected += float(self.sidecar[offer_key(o)]["p_pub"]) * o.hours
            for h in range(H):
                t = self.start + timedelta(hours=h)
                if o.start <= t and t + timedelta(hours=1) <= o.end:
                    staff[h] += 1
        vals = [
            float(len(coord)),
            float(len(reinf)),
            1.0 if not plan.actions else 0.0,
            float(plan.interventions),
            float(plan.reinforcement_hours),
            *hist,
            *staff,
            expected,
        ]
        return list(B1_NAMES), vals

    def row(self, plan: Plan, family: str) -> tuple[list[str], list[float]]:
        if family not in {"M_agg", "M_ent"}:
            raise ValueError(family)
        b1n, b1 = self._b1(plan)
        names, vals = [*self.b0_names, *b1n], [*self.b0, *b1]
        if family == "M_agg":
            return names, vals
        target = {a.target: hour_index(self.start, a.window_start) for a in plan.actions if a.type == "coordinate_discharge"}
        selected = {a.target for a in plan.actions if a.type == "reinforcement"}
        stays = sorted(
            self.stay_public[sid] + ([1.0, 1.0, float(target[sid]), 1.0] if sid in target else [0.0, 0.0, 0.0, 0.0])
            for sid in self.stay_public
        )
        width = len(self.STAY_PUBLIC_NAMES) + len(self.STAY_LINK_NAMES)
        stays += [[0.0] * width for _ in range(N_STAY - len(stays))]
        offers = sorted(
            self.offer_public[oid] + [1.0 if oid in selected else 0.0] for oid in self.offer_public
        )
        owidth = len(self.OFFER_PUBLIC_NAMES) + 1
        offers += [[0.0] * owidth for _ in range(N_OFFER - len(offers))]
        adms = [*self.adm_rows, *([[0.0] * len(self.ADM_NAMES)] * (N_ADM - len(self.adm_rows)))]
        for i, slot in enumerate(stays):
            names += [f"B2.stay{i}.{n}" for n in [*self.STAY_PUBLIC_NAMES, *self.STAY_LINK_NAMES]]
            vals += slot
        for i, slot in enumerate(offers):
            names += [f"B3.offer{i}.{n}" for n in [*self.OFFER_PUBLIC_NAMES, *self.OFFER_LINK_NAMES]]
            vals += slot
        for i, slot in enumerate(adms):
            names += [f"B4.admission{i}.{n}" for n in self.ADM_NAMES]
            vals += slot
        return names, vals


B1_NAMES = [
    "B1.n_coordinations", "B1.n_reinforcements", "B1.is_habitual", "B1.interventions",
    "B1.planned_reinforcement_hours", *[f"B1.coord_target_by_hour.{i}" for i in range(H)],
    *[f"B1.reinforcement_staff_by_hour.{i}" for i in range(H)], "B1.expected_reinforcement_hours",
]


def static_names(family: str) -> list[str]:
    """Feature names known without generating any snapshot (used for the E0 commitment)."""
    names = [*_layout_names("B0", B0_LAYOUT), *B1_NAMES]
    if family == "M_agg":
        return names
    sf = SnapshotFeatures
    for i in range(N_STAY):
        names += [f"B2.stay{i}.{n}" for n in [*sf.STAY_PUBLIC_NAMES, *sf.STAY_LINK_NAMES]]
    for i in range(N_OFFER):
        names += [f"B3.offer{i}.{n}" for n in [*sf.OFFER_PUBLIC_NAMES, *sf.OFFER_LINK_NAMES]]
    for i in range(N_ADM):
        names += [f"B4.admission{i}.{n}" for n in sf.ADM_NAMES]
    return names


def schema_fingerprint(names_agg: list[str] | None = None, names_ent: list[str] | None = None) -> str:
    names_agg = names_agg if names_agg is not None else static_names("M_agg")
    names_ent = names_ent if names_ent is not None else static_names("M_ent")
    body = {
        "schema": SCHEMA,
        "M_agg": names_agg,
        "M_ent": names_ent,
        "vocab": {"obstacle": list(OBSTACLE_VOCAB), "bed": BED_STATUS, "auth": AUTH, "dest": DEST,
                  "transport": TRANSPORT, "source": SOURCES, "confirmation": CONFIRM},
        "slots": {"stay": N_STAY, "offer": N_OFFER, "admission": N_ADM},
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
