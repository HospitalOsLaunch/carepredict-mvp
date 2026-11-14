"""Reference hybrid backend: explicit rules + conditional sampling of unknowns (P2).

Information boundary
--------------------
``forecast(public_snapshot, plan, config)`` receives only the PublicSnapshot. Unknown
delays (readiness, transport lead, cleaning, arrival) are sampled from the PUBLIC
distributions declared in the snapshot, with keyed innovations shared by all plans
(seed | scenario | mechanism | entity), so exogenous primitives are paired across plans
and do not depend on the order of draws (T22). The private realisation of an episode lives in
a separate ``PrivateTruth`` that only the evaluation simulator / an explicitly private oracle
receives; such a backend declares ``reads_private=True`` and is refused as a product backend
(T04). ``check_isolation`` runs a backend with two different private truths and fails if its
public output changes (T03/T04).

Safe profile: the historical "pressure discharges" mechanism of v041 (dis_h=h+4 when
h+4 < ready_h <= h+24) does not exist here and the profile flag must be false (T07).
Departures, cleaning, transport and admissions follow explicit precedence rules; an
independent checker re-verifies them from the event log (no cleaning before departure, no
double occupancy, no fictitious capacity, conservation).
"""

from __future__ import annotations

import hashlib
import inspect
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from fractions import Fraction
from typing import Any, Protocol

from hospitalos.hybrid.innovations import uniform

from .clock import local_hour
from .contracts import (
    BackendInfo,
    Distribution,
    HourPoint,
    Plan,
    PlanEvaluation,
    PlanMetrics,
    PublicSnapshot,
    ReinforcementOption,
)
from .eligibility import eligible_for_auto_discharge
from .resources import coverage, hour_index, staff_per_hour, team_capacity

BACKEND_NAME = "reference_hybrid"
BACKEND_VERSION = "1.0.0"
SKILLS = ("IDE", "AS")


class LeakageError(RuntimeError):
    """A backend reads or depends on the private future of the evaluated episode."""


class Provider(Protocol):
    reads_private: bool

    def draw(self, mechanism: str, entity: str, dist: Distribution) -> int: ...


@dataclass(frozen=True)
class SampledProvider:
    """Samples public distributions with keyed innovations (no hidden state, no truth)."""

    seed: int
    scenario: int = 0
    reads_private: bool = False

    def draw(self, mechanism: str, entity: str, dist: Distribution) -> int:
        u = Fraction(uniform(self.seed, self.scenario, mechanism, entity)).limit_denominator(
            2**53
        )
        total = sum(dist.weights)
        acc = 0
        for value, weight in zip(dist.support, dist.weights, strict=True):
            acc += weight
            if u < Fraction(acc, total):
                return value
        return dist.support[-1]


@dataclass(frozen=True)
class PrivateTruth:
    """Realised primitives of ONE synthetic episode. Never given to a product backend."""

    values: Mapping[str, Mapping[str, int]]
    legacy_private_fields: Mapping[str, Any] = field(default_factory=dict)  # e.g. ready_h

    @classmethod
    def from_fixture(cls, raw: Mapping[str, Any]) -> PrivateTruth:
        return cls(values=raw["primitives"], legacy_private_fields=raw.get("legacy", {}))


@dataclass(frozen=True)
class TruthProvider:
    truth: PrivateTruth
    reads_private: bool = True

    def draw(self, mechanism: str, entity: str, dist: Distribution) -> int:
        return int(self.truth.values[mechanism][entity])


# --------------------------------------------------------------------------- decisions


@dataclass(frozen=True)
class Decisions:
    coordinated: Mapping[str, tuple[int, str]]  # stay -> (target hour, basis)
    locked_discharges: Mapping[str, tuple[int, str]]  # stay -> (exact hour, basis)
    extensions: Mapping[str, tuple[int, str]]  # stay -> (departure hour, basis)
    reinforcements: tuple[ReinforcementOption, ...]


def decisions_from_plan(plan: Plan, snapshot: PublicSnapshot, start: datetime) -> Decisions:
    coordinated: dict[str, tuple[int, str]] = {}
    locked: dict[str, tuple[int, str]] = {}
    ext: dict[str, tuple[int, str]] = {}
    options = {r.option_id: r for r in snapshot.reinforcements}
    reinforcements = []
    for a in plan.actions:
        h = hour_index(start, a.window_start)
        if a.type == "coordinate_discharge":
            coordinated[a.target] = (h, a.basis)
        elif a.type == "locked_discharge":
            locked[a.target] = (h, a.basis)
        elif a.type == "locked_extension":
            ext[a.target] = (h, a.basis)
        elif a.type == "reinforcement":
            if a.target not in options:
                raise ValueError(f"Unknown reinforcement option {a.target}")
            reinforcements.append(options[a.target])
    return Decisions(coordinated, locked, ext, tuple(reinforcements))


# --------------------------------------------------------------------------- one world run


@dataclass
class Run:
    hours: int
    departures: dict[str, int]
    admissions: dict[str, int]
    arrivals: dict[str, int]
    bed_clean_at: dict[str, list[int]]
    events: list[tuple[int, str, str, str]]  # (hour, kind, subject, detail)
    demand: dict[str, list[int]]
    uncovered_unit: list[int]
    uncovered_skill: dict[str, list[int]]
    cleaning_jobs: list[tuple[str, str, int, int]]  # (bed, cause, start, duration)
    uncovered_waiting: list[int]
    shortfall: list[int]
    staff_scheduled: dict[str, list[int]]
    staff_extra: dict[str, list[int]]
    staff_required: dict[str, list[int]]
    waiting: list[int]
    clean_free: list[int]
    blockers: list[int]
    beds_returned: int
    violations: list[str]
    warnings: list[str]


def _care_minutes(profile_rows: Any, skill: str, day: bool) -> int:
    for c in profile_rows:
        if c.skill == skill:
            return c.day_minutes_per_hour if day else c.night_minutes_per_hour
    return 0


def simulate(
    snapshot: PublicSnapshot,
    profile: Mapping[str, Any],
    start: datetime,
    hours: int,
    decisions: Decisions,
    provider: Provider,
) -> Run:
    if profile.get("pressure_discharges_enabled", False):
        raise ValueError("Safe profile required: pressure discharges must be disabled")
    events: list[tuple[int, str, str, str]] = []
    violations: list[str] = []
    warnings: list[str] = []
    beds = {b.bed_id: b for b in snapshot.beds}
    stays = {s.stay_id: s for s in snapshot.stays}
    transport, transport_known = team_capacity(snapshot.teams, "transport", start, hours)
    cleaning, cleaning_known = team_capacity(snapshot.teams, "cleaning", start, hours)
    transport_left = list(transport)
    habitual_local = int(profile["habitual_practice"]["discharge_organisation_local_hour"])
    organisation = next(
        (h for h in range(hours) if local_hour(start + timedelta(hours=h)) == habitual_local),
        hours,
    )

    # ---- departures: locked first (fixed), then coordinated/habitual by desired hour
    requests: list[tuple[int, int, str, str, int]] = []  # (order, desired, stay, origin, ready)
    for sid, s in sorted(stays.items()):
        ready = None
        if s.ready_earliest is not None and s.ready_delay is not None:
            ready = max(0, hour_index(start, s.ready_earliest)) + provider.draw(
                "readiness", sid, s.ready_delay
            )
        lead = 0
        if s.transport_need in {"seated", "stretcher"} and s.transport_lead is not None:
            lead = provider.draw("transport_lead", sid, s.transport_lead)
        if sid in decisions.locked_discharges or sid in decisions.extensions:
            hour, basis = decisions.locked_discharges.get(sid) or decisions.extensions[sid]
            if basis != "hypothesis_only" and s.medical_authorization != "authorized":
                violations.append(f"locked_discharge_without_authorization:{sid}")
            if ready is not None and ready > hour:
                warnings.append(f"lock_precondition_unmet:{sid}:ready_after_locked_hour")
            if lead > hour:
                warnings.append(f"lock_precondition_unmet:{sid}:transport_lead")
            requests.append((0, hour, sid, "locked", ready if ready is not None else 0))
        elif sid in decisions.coordinated:
            target, _ = decisions.coordinated[sid]
            if not eligible_for_auto_discharge(s):
                violations.append(f"coordination_on_ineligible_stay:{sid}")
                continue
            assert ready is not None
            requests.append((1, max(target, ready, lead), sid, "coordinated", ready))
        elif eligible_for_auto_discharge(s):
            assert ready is not None
            if s.planned_departure is not None:
                base = hour_index(start, s.planned_departure)
            else:
                base = organisation + lead
            requests.append((1, max(base, ready), sid, "habitual", ready))
    departures: dict[str, int] = {}
    delayed: dict[str, tuple[int, int]] = {}
    for order, desired, sid, origin, ready in sorted(requests):
        s = stays[sid]
        needs = s.transport_need in {"seated", "stretcher"}
        if desired >= hours:
            continue
        hour = desired
        if needs:
            if origin == "locked":
                if not transport_known[hour] or transport_left[hour] <= 0:
                    violations.append(f"locked_transport_unavailable:{sid}:h{hour}")
                    continue
            else:
                while hour < hours and transport_left[hour] <= 0:
                    hour += 1
                if hour >= hours:
                    if not all(transport_known[desired:]):
                        warnings.append(f"transport_capacity_unknown:{sid}")
                    delayed[sid] = (desired, hours)
                    continue
                if hour != desired:
                    events.append((desired, "rescheduled_to_next_transport_slot", sid, f"h{hour}"))
                    delayed[sid] = (desired, hour)
            transport_left[hour] -= 1
            events.append((hour, "transport_used", sid, origin))
        departures[sid] = hour
        events.append((hour, "departure", sid, origin))

    # ---- cleaning: only after departure; FIFO by dirty time; finite concurrent capacity
    busy = [0] * hours
    cleaning_jobs: list[tuple[str, str, int, int]] = []
    jobs: list[tuple[int, str, str]] = []  # (ready_from, bed, cause)
    bed_clean_at: dict[str, list[int]] = {}
    for b in snapshot.beds:
        if b.status == "dirty":
            jobs.append((0, b.bed_id, "initial"))
        elif b.status == "cleaning":
            assert b.cleaning is not None
            remaining = provider.draw("cleaning_remaining", b.bed_id, b.cleaning)
            for h in range(min(remaining, hours)):
                busy[h] += 1
            cleaning_jobs.append((b.bed_id, "in_progress", 0, remaining))
            bed_clean_at.setdefault(b.bed_id, []).append(remaining)
            events.append((0, "cleaning_start", b.bed_id, "in_progress"))
        elif b.status == "clean":
            bed_clean_at.setdefault(b.bed_id, []).append(0)
    for sid, h in departures.items():
        bed_id = stays[sid].bed_id
        assert bed_id is not None
        jobs.append((h + 1, bed_id, sid))
    returned = 0
    for ready_from, bed_id, cause in sorted(jobs):
        dist = beds[bed_id].cleaning or Distribution.point(1)
        duration = provider.draw("cleaning", f"{bed_id}|{cause}", dist)
        s = ready_from
        while s < hours and any(
            busy[x] >= cleaning[x] for x in range(s, min(s + duration, hours))
        ):
            s += 1
        if s >= hours:
            continue
        for x in range(s, min(s + duration, hours)):
            busy[x] += 1
        cleaning_jobs.append((bed_id, cause, s, duration))
        events.append((s, "cleaning_start", bed_id, cause))
        if s + duration <= hours:
            bed_clean_at.setdefault(bed_id, []).append(s + duration)
            events.append((s + duration, "bed_clean", bed_id, cause))
            if cause != "initial":
                returned += 1

    # ---- admissions: FIFO on the first clean, compatible, unoccupied bed (not a lever)
    occupied_from: dict[str, int] = {}  # bed -> hour of (re)occupation after it became clean
    free_from: dict[str, int] = {}
    for bed_id, times in bed_clean_at.items():
        free_from[bed_id] = min(times)
    arrivals: dict[str, int] = {}
    admissions: dict[str, int] = {}
    for req in sorted(
        snapshot.admissions,
        key=lambda r: (
            max(0, hour_index(start, r.expected_arrival))
            + provider.draw("arrival", r.request_id, r.arrival_delay),
            r.request_id,
        ),
    ):
        arrive = max(0, hour_index(start, req.expected_arrival)) + provider.draw(
            "arrival", req.request_id, req.arrival_delay
        )
        if arrive >= hours:
            continue
        arrivals[req.request_id] = arrive
        options = [
            (max(arrive, free_from[b]), b)
            for b in sorted(free_from)
            if b not in occupied_from
            and beds[b].status != "closed"
            and set(req.requirements) <= set(beds[b].capabilities)
        ]
        if not options:
            continue
        hour, bed_id = min(options)
        if hour >= hours:
            continue
        occupied_from[bed_id] = hour
        admissions[req.request_id] = hour
        events.append((hour, "admission", req.request_id, bed_id))

    # ---- staffing and care coverage per hour
    day = profile["day_local_hours"]
    discharge_task = profile["discharge_task_minutes"]
    reqs = {r.request_id: r for r in snapshot.admissions}
    demand = {k: [0] * hours for k in SKILLS}
    staff_required = {k: [0] * hours for k in SKILLS}
    sched: dict[str, list[int]] = {}
    extra: dict[str, list[int]] = {}
    for k in SKILLS:
        sched[k], extra[k] = staff_per_hour(snapshot, k, start, hours, decisions.reinforcements)
    uncovered_unit = [0] * hours
    uncovered_skill = {k: [0] * hours for k in SKILLS}
    uncovered_wait = [0] * hours
    shortfall = [0] * hours
    waiting = [0] * hours
    blockers = [0] * hours
    clean_free = [0] * hours
    for h in range(hours):
        is_day = day["start"] <= local_hour(start + timedelta(hours=h)) < day["end"]
        for k in SKILLS:
            base = 0
            tasks: list[tuple[int, int]] = []
            for sid, s in stays.items():
                if sid in departures and h > departures[sid]:
                    continue
                base += _care_minutes(s.care, k, is_day)
                tasks += [
                    (t.minutes, t.staff_required)
                    for t in s.tasks
                    if t.skill == k and hour_index(start, t.start) == h
                ]
                if departures.get(sid) == h and k in discharge_task:
                    tasks.append((int(discharge_task[k]), 1))
            for rid, a in admissions.items():
                if h >= a:
                    base += _care_minutes(reqs[rid].care, k, is_day)
                if h == a and k == "IDE" and reqs[rid].admission_task_minutes:
                    tasks.append((reqs[rid].admission_task_minutes, 1))
            for rid, arrive in arrivals.items():
                if arrive <= h < admissions.get(rid, hours):
                    minutes = _care_minutes(reqs[rid].care, k, is_day)
                    uncovered_wait[h] += minutes
                    uncovered_skill[k][h] += minutes
            cov = coverage(base, tasks, sched[k][h] + extra[k][h])
            demand[k][h] = cov.demand_minutes
            staff_required[k][h] = cov.staff_required
            uncovered_unit[h] += cov.uncovered_minutes
            uncovered_skill[k][h] += cov.uncovered_minutes
            shortfall[h] += cov.simultaneity_shortfall_minutes
        waiting[h] = sum(
            1 for rid, arrive in arrivals.items() if arrive <= h < admissions.get(rid, hours)
        )
        cleaning_started = {(bed, cause): st for bed, cause, st, _ in cleaning_jobs}
        blockers[h] = sum(1 for d, a in delayed.values() if d <= h < a) + sum(
            1
            for sid, dep in departures.items()
            if dep < h < cleaning_started.get((stays[sid].bed_id, sid), hours)
        )
        clean_free[h] = sum(
            1
            for b, f in free_from.items()
            if f <= h and (b not in occupied_from or occupied_from[b] > h)
            and beds[b].status != "closed"
        )
    return Run(
        hours, departures, admissions, arrivals, bed_clean_at, events, demand, uncovered_unit,
        uncovered_skill, cleaning_jobs, uncovered_wait, shortfall, sched, extra, staff_required, waiting, clean_free, blockers,
        returned, violations, warnings,
    )


# --------------------------------------------------------------------------- invariants


def check_invariants(
    snapshot: PublicSnapshot, start: datetime, run: Run, hypothetical_ok: bool
) -> list[str]:
    """Independent re-verification of the event log (does not trust the simulator)."""
    problems: list[str] = []
    stays = {s.stay_id: s for s in snapshot.stays}
    transport, _ = team_capacity(snapshot.teams, "transport", start, run.hours)
    cleaning, _ = team_capacity(snapshot.teams, "cleaning", start, run.hours)
    used = [0] * run.hours
    for h, kind, _, _ in run.events:
        if kind == "transport_used":
            used[h] += 1
    problems += [f"transport_over_capacity:h{h}" for h in range(run.hours) if used[h] > transport[h]]
    departure_of_bed = {stays[s].bed_id: h for s, h in run.departures.items()}
    for h, kind, subject, cause in run.events:
        if kind == "cleaning_start" and cause not in {"initial", "in_progress"}:
            if subject not in departure_of_bed or h <= departure_of_bed[subject]:
                problems.append(f"cleaning_before_departure:{subject}")
    for sid, h in run.departures.items():
        if stays[sid].medical_authorization != "authorized" and not hypothetical_ok:
            problems.append(f"departure_without_authorization:{sid}")
    beds_taken: dict[str, int] = {}
    for h, kind, rid, bed in run.events:
        if kind != "admission":
            continue
        if bed in beds_taken:
            problems.append(f"double_occupancy:{bed}")
        beds_taken[bed] = h
        clean_times = [t for t in run.bed_clean_at.get(bed, []) if t <= h]
        if not clean_times:
            problems.append(f"admission_to_unclean_bed:{bed}")
        initial = next(b for b in snapshot.beds if b.bed_id == bed)
        if initial.status == "occupied":
            occupant = next((s for s in snapshot.stays if s.bed_id == bed), None)
            if occupant is None or run.departures.get(occupant.stay_id, run.hours) >= h:
                problems.append(f"admission_before_departure:{bed}")
    present_end = (
        len(snapshot.stays) - sum(1 for h in run.departures.values() if h < run.hours)
        + len(run.admissions)
    )
    if present_end > len(snapshot.beds):
        problems.append("conservation_beds_exceeded")
    concurrent = [0] * run.hours
    for _, _, st, duration in run.cleaning_jobs:
        for x in range(st, min(st + duration, run.hours)):
            concurrent[x] += 1
    problems += [
        f"cleaning_over_capacity:h{h}"
        for h in range(run.hours)
        if concurrent[h] > cleaning[h] and not all(c[1] == "in_progress" for c in run.cleaning_jobs
                                                    if c[2] <= h < c[2] + c[3])
    ]
    return problems


# --------------------------------------------------------------------------- aggregation


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def pressure_scores(run: Run, score: Mapping[str, Any] | None) -> list[int] | None:
    if not score or score.get("status") != "EXPERIMENTAL_SYNTHETIC":
        return None
    c = score["coefficients"]
    out = []
    for h in range(run.hours):
        raw = (
            (run.uncovered_unit[h] + run.uncovered_waiting[h]) / c["uncovered_minutes_divisor"]
            + c["waiting_patient"] * run.waiting[h]
            + c["logistic_blocker"] * run.blockers[h]
            + (c["no_clean_free_bed"] if run.clean_free[h] == 0 else 0)
        )
        out.append(min(10, math.floor(raw + 0.5)))
    return out


def summarise(
    runs: list[Run],
    plan: Plan,
    start: datetime,
    score: Mapping[str, Any] | None,
) -> tuple[PlanMetrics, tuple[HourPoint, ...]]:
    hours = runs[0].hours
    scores = [pressure_scores(r, score) for r in runs]
    configured = scores[0] is not None
    trajectory = []
    for h in range(hours):
        ts = start + timedelta(hours=h)
        trajectory.append(
            HourPoint(
                hour_index=h,
                start_utc=ts,
                local_label=f"{local_hour(ts):02d}:00",
                staff_scheduled={k: _mean([r.staff_scheduled[k][h] for r in runs]) for k in SKILLS},
                staff_reinforcement={k: _mean([r.staff_extra[k][h] for r in runs]) for k in SKILLS},
                staff_required={k: _mean([r.staff_required[k][h] for r in runs]) for k in SKILLS},
                demand_minutes={k: _mean([r.demand[k][h] for r in runs]) for k in SKILLS},
                uncovered_in_unit_minutes=_mean([r.uncovered_unit[h] for r in runs]),
                uncovered_waiting_minutes=_mean([r.uncovered_waiting[h] for r in runs]),
                simultaneity_shortfall_minutes=_mean([r.shortfall[h] for r in runs]),
                waiting_patients=_mean([r.waiting[h] for r in runs]),
                clean_free_beds=_mean([r.clean_free[h] for r in runs]),
                logistic_blockers=_mean([r.blockers[h] for r in runs]),
                pressure_score=_mean([s[h] for s in scores if s is not None]) if configured else None,
            )
        )
    totals = [sum(r.uncovered_unit) + sum(r.uncovered_waiting) for r in runs]
    threshold = score.get("threshold") if configured and score else None
    peak = max((p.pressure_score or 0.0) for p in trajectory) if configured else None
    metrics = PlanMetrics(
        uncovered_care_minutes=_mean(totals),
        uncovered_in_unit_minutes=_mean([sum(r.uncovered_unit) for r in runs]),
        uncovered_waiting_minutes=_mean([sum(r.uncovered_waiting) for r in runs]),
        uncovered_by_skill={k: _mean([sum(r.uncovered_skill[k]) for r in runs]) for k in SKILLS},
        simultaneity_shortfall_minutes=_mean([sum(r.shortfall) for r in runs]),
        waiting_patient_hours=_mean([sum(r.waiting) for r in runs]),
        admissions_by_end=_mean([len(r.admissions) for r in runs]),
        departures_by_end=_mean([len(r.departures) for r in runs]),
        beds_returned=_mean([r.beds_returned for r in runs]),
        reinforcement_hours=plan.reinforcement_hours,
        interventions=plan.interventions,
        peak_pressure=peak,
        peak_pressure_hour=next(
            (p.hour_index for p in trajectory if p.pressure_score == peak), None
        ) if configured else None,
        hours_above_threshold=_mean(
            [sum(1 for v in s if v >= threshold) for s in scores if s is not None]
        ) if configured and threshold is not None else None,
        worst_scenario_uncovered_minutes=float(max(totals)),
        best_scenario_uncovered_minutes=float(min(totals)),
        max_total_staff_required={
            k: max(p.staff_required[k] for p in trajectory) for k in SKILLS
        },
        max_additional_staff_required={
            k: max(max(0.0, p.staff_required[k] - p.staff_scheduled[k]) for p in trajectory)
            for k in SKILLS
        },
    )
    return metrics, tuple(trajectory)


# --------------------------------------------------------------------------- backends


def _code_sha(obj: Any) -> str:
    return hashlib.sha256(inspect.getsource(obj).encode()).hexdigest()


@dataclass(frozen=True)
class ForecastConfig:
    profile: Mapping[str, Any]
    score: Mapping[str, Any] | None
    seeds: tuple[int, ...]
    start: datetime
    hours: int


class ReferenceForecaster:
    """Product backend. Its signature cannot receive a private truth."""

    reads_private = False

    def info(self) -> BackendInfo:
        import sys

        module = sys.modules[__name__]
        return BackendInfo(
            name=BACKEND_NAME, version=BACKEND_VERSION, code_sha256=_code_sha(module),
            reads_private=False, product_allowed=True,
        )

    def runs(self, snapshot: PublicSnapshot, plan: Plan, config: ForecastConfig,
             drop_unconfirmed: bool = False) -> list[Run]:
        decisions = decisions_from_plan(plan, snapshot, config.start)
        if drop_unconfirmed:
            decisions = Decisions(
                decisions.coordinated, decisions.locked_discharges, decisions.extensions,
                tuple(r for r in decisions.reinforcements if r.confirmation == "confirmed"),
            )
        return [
            simulate(snapshot, config.profile, config.start, config.hours, decisions,
                     SampledProvider(seed))
            for seed in config.seeds
        ]

    def forecast(self, snapshot: PublicSnapshot, plan: Plan, config: ForecastConfig) -> PlanEvaluation:
        if not isinstance(snapshot, PublicSnapshot):
            raise LeakageError("forecast() accepts a PublicSnapshot only")
        runs = self.runs(snapshot, plan, config)
        hypothetical = any(a.basis == "hypothesis_only" for a in plan.actions)
        violations = sorted({v for r in runs for v in r.violations} | {
            v for r in runs for v in check_invariants(snapshot, config.start, r, hypothetical)
        })
        warnings = sorted({w for r in runs for w in r.warnings})
        metrics, trajectory = summarise(runs, plan, config.start, config.score)
        conditional = tuple(
            a.target for a in plan.actions if a.type == "reinforcement" and a.conditional
        )
        confirmed_only = None
        if conditional:
            confirmed_only, _ = summarise(
                self.runs(snapshot, plan, config, drop_unconfirmed=True), plan, config.start,
                config.score,
            )
        return PlanEvaluation(
            plan=plan,
            admissible=not violations,
            violations=tuple(violations),
            warnings=tuple(warnings),
            conditional_on=conditional,
            metrics=metrics,
            trajectory=trajectory,
            confirmed_only=confirmed_only,
            per_scenario_uncovered=tuple(
                float(sum(r.uncovered_unit) + sum(r.uncovered_waiting)) for r in runs
            ),
        )


class PrivateOracle:
    """Evaluation-only backend initialised from the private truth. NOT a product backend."""

    reads_private = True

    def __init__(self, truth: PrivateTruth) -> None:
        self.truth = truth

    def info(self) -> BackendInfo:
        return BackendInfo(
            name="private_oracle", version=BACKEND_VERSION, code_sha256=_code_sha(PrivateOracle),
            reads_private=True, product_allowed=False,
        )

    def outcome(self, snapshot: PublicSnapshot, plan: Plan, config: ForecastConfig) -> Run:
        return simulate(snapshot, config.profile, config.start, config.hours,
                        decisions_from_plan(plan, snapshot, config.start),
                        TruthProvider(self.truth))


def assert_product_backend(backend: Any) -> None:
    if getattr(backend, "reads_private", True):
        raise LeakageError(f"{type(backend).__name__} reads private truth: blocked as product")


def check_isolation(
    make_backend: Any,
    snapshot: PublicSnapshot,
    plan: Plan,
    config: ForecastConfig,
    truth_a: PrivateTruth,
    truth_b: PrivateTruth,
) -> None:
    """Behavioural leak test: same public input, two private truths => identical output."""
    outputs = []
    for truth in (truth_a, truth_b):
        backend = make_backend(truth)
        if hasattr(backend, "forecast"):
            out = backend.forecast(snapshot, plan, config).model_dump_json()
        else:
            run = backend.outcome(snapshot, plan, config)
            out = repr((run.departures, run.admissions, run.uncovered_unit, run.uncovered_waiting))
        outputs.append(out)
    if outputs[0] != outputs[1]:
        raise LeakageError("Public output depends on the private realisation: backend blocked")
