"""recommend / simulate / review — one evaluation core for auto and manual modes (P3).

Auto mode needs no user scenario: it builds the admissible universe from the snapshot and
selects with the versioned lexicographic objective. Manual mode only changes where the
constraints come from (ScenarioLocks); the forecaster, rules and objective are identical.
Locked decisions are never modified to improve the score. ``review`` never sends a command.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from . import ENGINE_VERSION
from .candidates import enumerate_plans, make_plan, reinforcement_action
from .clock import CivilTimeError, display, utc
from .contracts import (
    ActionSpec,
    ForecastBundle,
    LockedDischarge,
    LockedExtension,
    LockedReinforcement,
    PlanEvaluation,
    PublicSnapshot,
    Recommendation,
    ReviewResult,
    ScenarioLocks,
    SearchReport,
)
from .eligibility import (
    eligible_for_auto_discharge,
    lock_precondition_issues,
    plan_precondition_errors,
    revalidate_discharge,
)
from .reference_forecaster import ForecastConfig, ReferenceForecaster, assert_product_backend
from .resources import (
    ResourceLedger,
    hour_index,
    lending_violations,
    option_admissibility,
    roster_known,
    team_capacity,
)
from .snapshot import CONFIG_DIR, load_json, load_profile, sha


class IdempotencyConflict(ValueError):
    """F04: an idempotency key reused for a different request content."""


def settings_fingerprint(settings: Settings) -> str:
    """F08: full configuration content (not only version labels) + backend code."""
    return sha(
        {
            "profile": dict(settings.profile),
            "objective": dict(settings.objective),
            "score": dict(settings.score) if settings.score else None,
            "backend": settings.backend.info().model_dump(mode="json"),
        }
    )


def run_fingerprint(settings: Settings, start: datetime, hours: int) -> str:
    return sha(
        {
            "settings": settings_fingerprint(settings),
            "seeds": list(settings.profile["forecast"]["selection_seeds"]),
            "horizon": [start.isoformat(), hours],
        }
    )


class HorizonError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class Settings:
    profile: Mapping[str, Any]
    objective: Mapping[str, Any]
    score: Mapping[str, Any] | None
    backend: Any = field(default_factory=ReferenceForecaster)

    @classmethod
    def default(cls, score: bool = True) -> Settings:
        return cls(
            profile=load_profile(),
            objective=load_json(CONFIG_DIR / "OBJECTIVE_CONFIG.json"),
            score=load_json(CONFIG_DIR / "PRESSURE_SCORE_CONFIG.json") if score else None,
        )


def score_descriptor(score: Mapping[str, Any] | None) -> dict[str, Any]:
    if not score or score.get("status") != "EXPERIMENTAL_SYNTHETIC":
        return {"score_status": "UNCONFIGURED", "components_only": True}
    return {
        "score_status": "EXPERIMENTAL_SYNTHETIC",
        "score_id": score["score_id"],
        "version": score["version"],
        "formula_sha256": sha({k: score[k] for k in ("formula", "coefficients", "threshold")}),
        "threshold": score["threshold"],
        "comparable_only_with_same_formula_sha256": True,
    }


def resolve_horizon(
    snapshot: PublicSnapshot, profile: Mapping[str, Any], locks: ScenarioLocks | None
) -> tuple[datetime, datetime, int]:
    start = snapshot.as_of
    supported = int(profile["supported_horizon_hours"])
    if locks is not None and locks.deadline is not None:
        try:
            end = locks.deadline.resolve(start)
        except CivilTimeError as error:
            raise HorizonError(error.code, str(error)) from error
    else:
        end = start + timedelta(hours=supported)
    hours = (end - start) / timedelta(hours=1)
    if hours <= 0 or hours != int(hours):
        raise HorizonError("INVALID_HORIZON", f"{display(start)} -> {display(end)}")
    if hours > supported:
        raise HorizonError(
            "UNSUPPORTED_HORIZON",
            f"{int(hours)} h real UTC duration > {supported} h supported "
            f"({display(start)} -> {display(end)}); never truncated",
        )
    return start, end, int(hours)


def _objective_key(e: PlanEvaluation, best_tier1: float, tolerance: float, order: int):
    within = e.metrics.uncovered_care_minutes <= best_tier1 + tolerance
    return (
        not within,
        e.metrics.reinforcement_hours,
        e.metrics.interventions,
        e.metrics.uncovered_care_minutes,
        order,
    )


def select(evaluations: list[PlanEvaluation], objective: Mapping[str, Any]) -> PlanEvaluation:
    tier1 = next(t for t in objective["tiers"] if t["rank"] == 1)
    tolerance = float(tier1["equivalence_tolerance"])
    admissible = [(i, e) for i, e in enumerate(evaluations) if e.admissible]
    best = min(e.metrics.uncovered_care_minutes for _, e in admissible)
    return min(admissible, key=lambda ie: _objective_key(ie[1], best, tolerance, ie[0]))[1]


def _distinct(a: PlanEvaluation, b: PlanEvaluation) -> bool:
    def signature(e: PlanEvaluation) -> tuple[frozenset[str], bool]:
        stays = frozenset(x.target for x in e.plan.actions if x.type == "coordinate_discharge")
        return stays, any(x.type == "reinforcement" for x in e.plan.actions)

    return signature(a) != signature(b)


def _explain(chosen: PlanEvaluation, baseline: PlanEvaluation, tolerance: float) -> list[str]:
    c, b = chosen.metrics, baseline.metrics
    lines = [
        f"tier1 uncovered_care_minutes: habitual {b.uncovered_care_minutes} -> plan "
        f"{c.uncovered_care_minutes} (delta {round(c.uncovered_care_minutes - b.uncovered_care_minutes, 3)}, "  # noqa: E501
        f"equivalence tolerance {tolerance})",
        f"tier2 reinforcement_hours: {c.reinforcement_hours}",
        f"tier3 interventions: {c.interventions}",
        f"reported waiting_patient_hours: habitual {b.waiting_patient_hours} -> plan {c.waiting_patient_hours}",  # noqa: E501
        f"reported beds_returned: habitual {b.beds_returned} -> plan {c.beds_returned}",
    ]
    return lines


def _recommendation(
    *,
    status: str,
    mode: str,
    snapshot: PublicSnapshot,
    settings: Settings,
    reasons: list[str],
    diagnostics: list[str],
    bundle: ForecastBundle | None,
    baseline: PlanEvaluation | None = None,
    primary: PlanEvaluation | None = None,
    alternative: PlanEvaluation | None = None,
    locked: PlanEvaluation | None = None,
    locks: ScenarioLocks | None = None,
    approvable: bool = False,
) -> Recommendation:
    """Identity covers the full configuration and the result (F08): one id, one content."""
    conditions: list[str] = []
    uncertainties: list[str] = []
    if primary is not None:
        for a in primary.plan.actions:
            conditions += [f"{a.action_id}: {p}" for p in a.preconditions]
            if a.conditional:
                conditions.append(
                    f"{a.action_id}: requested, NOT confirmed -> result conditional on its presence"
                )
        m = primary.metrics
        uncertainties = [
            f"{len(primary.per_scenario_uncovered)} forecast scenarios (selection seeds, in-sample)",  # noqa: E501
            f"uncovered minutes range over scenarios: {m.best_scenario_uncovered_minutes}"
            f"..{m.worst_scenario_uncovered_minutes}",
            "pointwise scenario means; not a simultaneous guarantee over the horizon",
            "synthetic declared distributions; no real-world calibration",
            *primary.warnings,
        ]
    body = {
        "fp": snapshot.fingerprint,
        "mode": mode,
        "status": status,
        "objective": settings.objective["objective_id"],
        "engine": ENGINE_VERSION,
        "locks": locks.model_dump(mode="json") if locks else None,
        "primary": primary.plan.plan_id if primary else None,
        "settings": settings_fingerprint(settings),
        "bundle": bundle.bundle_id if bundle else None,
        "diagnostics": list(diagnostics),
        "approvable": approvable,
    }
    validity = timedelta(minutes=int(settings.profile["recommendation_validity_minutes"]))
    return Recommendation(
        recommendation_id="reco-" + sha(body)[:16],
        status=status,  # type: ignore[arg-type]
        mode=mode,  # type: ignore[arg-type]
        created_at=snapshot.as_of,
        valid_until=snapshot.as_of + validity,
        snapshot_id=snapshot.snapshot_id,
        snapshot_fingerprint=snapshot.fingerprint,
        objective_version=f"{settings.objective['objective_id']}@{settings.objective['version']}",
        engine_version=ENGINE_VERSION,
        reasons=tuple(reasons),
        conditions=tuple(conditions),
        uncertainties=tuple(uncertainties),
        diagnostics=tuple(diagnostics),
        approvable=approvable,
        baseline_plan_id=baseline.plan.plan_id if baseline else None,
        primary_plan_id=primary.plan.plan_id if primary else None,
        alternative_plan_id=alternative.plan.plan_id if alternative else None,
        locked_plan_id=locked.plan.plan_id if locked else None,
        locks=locks,
        bundle=bundle,
    )


def required_skills(snapshot: PublicSnapshot, profile: Mapping[str, Any]) -> list[str]:
    """Skills with a declared care need (stays, tasks, admissions, discharge work)."""
    skills = set(profile["discharge_task_minutes"])
    for s in snapshot.stays:
        skills |= {c.skill for c in s.care if c.day_minutes_per_hour or c.night_minutes_per_hour}
        skills |= {t.skill for t in s.tasks}
    for a in snapshot.admissions:
        skills |= {c.skill for c in a.care if c.day_minutes_per_hour or c.night_minutes_per_hour}
    return sorted(skills)


def _data_gaps(
    snapshot: PublicSnapshot,
    profile: Mapping[str, Any],
    start: datetime,
    hours: int,
    departing: frozenset[str] = frozenset(),
) -> tuple[list[str], list[str]]:
    """Returns (gaps -> abstention, assumptions used -> reported). Unknown is never zero."""
    gaps = list(snapshot.issues)
    assumptions: list[str] = []
    for skill in required_skills(snapshot, profile):  # F07: every required skill
        known = roster_known(snapshot, skill, start, hours)
        missing = [h for h, k in enumerate(known) if not k]
        if missing:
            gaps.append(
                f"roster_unknown:{skill}:{display(start + timedelta(hours=missing[0]))}"
                f"..{display(start + timedelta(hours=missing[-1] + 1))}"
            )
    _, cleaning_known = team_capacity(snapshot.teams, "cleaning", start, hours)
    if not any(cleaning_known):
        gaps.append("cleaning_capacity_unknown")
    # F06: beds that any evaluated plan may free need a known cleaning duration, or a
    # configured, versioned replacement assumption that is reported.
    may_leave = {
        s.stay_id for s in snapshot.stays if eligible_for_auto_discharge(s)
    } | set(departing)
    beds = {b.bed_id: b for b in snapshot.beds}
    assumption = profile.get("unknown_cleaning_assumption")
    for s in snapshot.stays:
        bed = beds.get(s.bed_id or "")
        if s.stay_id in may_leave and bed is not None and bed.cleaning is None:
            if assumption:
                assumptions.append(
                    f"assumed_cleaning_duration:{bed.bed_id}:{assumption['id']}@"
                    f"{assumption['version']}"
                )
            else:
                gaps.append(f"cleaning_duration_unknown:{bed.bed_id}")
    return gaps, assumptions


def _bundle(snapshot, settings, start, end, hours, evaluations, report, mode) -> ForecastBundle:
    info = settings.backend.info()
    config = {
        "run_fingerprint": run_fingerprint(settings, start, hours),
        "settings_sha256": settings_fingerprint(settings),
        "profile": f"{settings.profile['profile_id']}@{settings.profile['version']}",
        "objective": f"{settings.objective['objective_id']}@{settings.objective['version']}",
        "mode": mode,
        "pressure_discharges_enabled": settings.profile["pressure_discharges_enabled"],
    }
    body = {
        "fp": snapshot.fingerprint,
        "config": config,
        "evaluations": [e.model_dump(mode="json") for e in evaluations],
        "search": report.model_dump(mode="json"),
    }
    return ForecastBundle(
        bundle_id="fb-" + sha(body)[:16],
        backend=info,
        config=config,
        snapshot_id=snapshot.snapshot_id,
        snapshot_fingerprint=snapshot.fingerprint,
        horizon_start=start,
        horizon_end=end,
        horizon_hours=hours,
        selection_seeds=tuple(settings.profile["forecast"]["selection_seeds"]),
        assumptions=(
            "habitual practice HABITUAL-1 continues in every branch (care, arrivals, ordinary decisions)",  # noqa: E501
            "pressure discharges disabled for all policies",
            "unknown delays sampled from public declared distributions with keyed paired innovations",  # noqa: E501
            "admissions are not a lever; waiting patients' care counts as uncovered",
        ),
        search=report,
        evaluations=tuple(evaluations),
        score=score_descriptor(settings.score),
    )


def _config(settings: Settings, start: datetime, hours: int) -> ForecastConfig:
    return ForecastConfig(
        profile=settings.profile,
        score=settings.score,
        seeds=tuple(settings.profile["forecast"]["selection_seeds"]),
        start=start,
        hours=hours,
    )


def _with_onset(e: PlanEvaluation, baseline: PlanEvaluation) -> PlanEvaluation:
    onset = next(
        (
            p.hour_index
            for p, q in zip(e.trajectory, baseline.trajectory, strict=True)
            if p.model_dump(exclude={"local_label"}) != q.model_dump(exclude={"local_label"})
        ),
        None,
    )
    return e.model_copy(update={"effect_onset_hour": onset})


def recommend(
    snapshot: PublicSnapshot, settings: Settings | None = None, max_plans: int | None = None
) -> Recommendation:
    """Auto mode: no user scenario required (T15)."""
    settings = settings or Settings.default()
    assert_product_backend(settings.backend)
    try:
        start, end, hours = resolve_horizon(snapshot, settings.profile, None)
    except HorizonError as error:
        return _recommendation(
            status="INFEASIBLE",
            mode="auto",
            snapshot=snapshot,
            settings=settings,
            reasons=[error.code],
            diagnostics=[str(error)],
            bundle=None,
        )
    gaps, assumed = _data_gaps(snapshot, settings.profile, start, hours)
    if gaps:
        return _recommendation(
            status="INSUFFICIENT_DATA",
            mode="auto",
            snapshot=snapshot,
            settings=settings,
            reasons=["abstention_data_insufficient"],
            diagnostics=gaps,
            bundle=None,
        )
    validity = snapshot.as_of + timedelta(
        minutes=int(settings.profile["recommendation_validity_minutes"])
    )
    plans, report = enumerate_plans(
        snapshot, settings.profile, start, end, validity, "auto", limit=max_plans
    )
    config = _config(settings, start, hours)
    evaluations = [settings.backend.forecast(snapshot, p, config) for p in plans]
    baseline = evaluations[0]
    evaluations = [baseline] + [_with_onset(e, baseline) for e in evaluations[1:]]
    bundle = _bundle(snapshot, settings, start, end, hours, evaluations, report, "auto")
    if not baseline.admissible:
        return _recommendation(
            status="INFEASIBLE",
            mode="auto",
            snapshot=snapshot,
            settings=settings,
            reasons=["habitual_practice_invariant_failure"],
            diagnostics=list(baseline.violations),
            bundle=bundle,
            baseline=baseline,
        )
    chosen = select(evaluations, settings.objective)
    tolerance = float(
        next(t for t in settings.objective["tiers"] if t["rank"] == 1)["equivalence_tolerance"]
    )
    reasons = _explain(chosen, baseline, tolerance)
    if not report.complete:
        reasons.append(
            f"search incomplete: {report.evaluated}/{report.enumerated} plans evaluated; "
            "best among evaluated, no optimum claimed"
        )
    if chosen.plan.is_baseline:
        return _recommendation(
            status="NO_ACTION_PREFERRED",
            mode="auto",
            snapshot=snapshot,
            settings=settings,
            reasons=["habitual_practice_preferred_no_material_improvement", *reasons],
            diagnostics=assumed,
            bundle=bundle,
            baseline=baseline,
            primary=baseline,
            approvable=True,
        )
    alternatives = [
        e
        for e in evaluations
        if e.admissible
        and e is not chosen
        and not e.plan.is_baseline
        and _distinct(e, chosen)
        and e.metrics.uncovered_care_minutes < baseline.metrics.uncovered_care_minutes - tolerance
    ]
    alternative = min(
        alternatives,
        key=lambda e: (
            e.metrics.uncovered_care_minutes,
            e.metrics.reinforcement_hours,
            e.metrics.interventions,
        ),
        default=None,
    )
    residual = chosen.metrics.uncovered_care_minutes
    if residual > 0:
        reasons.append(f"plan remains insufficient: {residual} uncovered staff-minutes expected")
    return _recommendation(
        status="RECOMMENDATION_READY",
        mode="auto",
        snapshot=snapshot,
        settings=settings,
        reasons=["lexicographic_objective_improvement_requires_human_approval", *reasons],
        diagnostics=assumed,
        bundle=bundle,
        baseline=baseline,
        primary=chosen,
        alternative=alternative,
        approvable=True,
    )


# --------------------------------------------------------------------------- manual mode


def locked_actions(
    snapshot: PublicSnapshot,
    locks: ScenarioLocks,
    start: datetime,
    end: datetime,
    valid_until: datetime,
) -> tuple[tuple[ActionSpec, ...], list[str], list[str], bool]:
    """Returns (actions, contradictions, diagnostics, hypothetical)."""
    stays = {s.stay_id: s for s in snapshot.stays}
    options = {o.option_id: o for o in snapshot.reinforcements}
    actions: list[ActionSpec] = []
    contradictions: list[str] = []
    diagnostics: list[str] = []
    hypothetical = False
    seen: dict[str, str] = {}
    for lock in locks.locks:
        subject = lock.option_id if isinstance(lock, LockedReinforcement) else lock.stay_id
        if subject in seen:
            contradictions.append(f"contradictory_locks:{subject}:{seen[subject]}+{lock.kind}")
            continue
        seen[subject] = lock.kind
        if isinstance(lock, LockedReinforcement):
            option = options.get(lock.option_id)
            if option is None:
                contradictions.append(f"unknown_reinforcement_option:{lock.option_id}")
                continue
            if lock.include:
                ok, reason = option_admissibility(option, start, end)
                if not ok:
                    contradictions.append(
                        f"locked_reinforcement_inadmissible:{lock.option_id}:{reason}"
                    )
                    continue
                actions.append(reinforcement_action(snapshot, option, valid_until, "manual_lock"))
            continue
        stay = stays.get(lock.stay_id)
        if stay is None:
            contradictions.append(f"unknown_stay:{lock.stay_id}")
            continue
        at = lock.at if isinstance(lock, LockedDischarge) else lock.target_time
        if not (start <= at < end):
            contradictions.append(f"locked_time_outside_horizon:{lock.stay_id}:{display(at)}")
            continue
        basis = lock.basis
        if basis == "validated_instruction" and stay.medical_authorization != "authorized":
            diagnostics.append(
                f"validated_instruction_without_observed_authorization:{lock.stay_id} "
                "-> treated as hypothesis_only"
            )
            basis = "hypothesis_only"
        elif basis == "validated_instruction":
            # F01: same preconditions as an automatic action. The locked hour is kept
            # exactly; if a precondition is unmet (obstacle, readiness or transport lead
            # contradicted in some or all scenarios) the scenario stays a hypothesis.
            issues = [
                i
                for i in lock_precondition_issues(stay, start, at)
                if not i.startswith("medical_authorization")
            ]
            if issues:
                diagnostics.append(
                    f"validated_instruction_preconditions_unmet:{lock.stay_id}:"
                    f"{','.join(issues)} -> treated as hypothesis_only, time kept"
                )
                basis = "hypothesis_only"
        hypothetical = hypothetical or basis == "hypothesis_only"
        kind = "locked_discharge" if isinstance(lock, LockedDischarge) else "locked_extension"
        detail = (
            f"reference {display(lock.reference_time)} + {lock.extension_hours} h"
            if isinstance(lock, LockedExtension)
            else "fixed departure hour"
        )
        actions.append(
            ActionSpec(
                action_id=f"lock:{kind}:{lock.stay_id}:{at.strftime('%Y%m%dT%H%MZ')}",
                type=kind,  # type: ignore[arg-type]
                target=lock.stay_id,
                window_start=at,
                window_end=at + timedelta(hours=1),
                preconditions=(
                    detail,
                    f"basis:{basis}",
                    "user_lock_not_a_system_clinical_decision",
                ),
                resources=("transport_team",)
                if stay.transport_need in {"seated", "stretcher"}
                else (),
                interventions=0,
                validator="medecin",
                idempotency_key="lock-" + sha([kind, lock.stay_id, at.isoformat()])[:16],
                valid_until=valid_until,
                origin="manual_lock",
                basis=basis,  # type: ignore[arg-type]
            )
        )
    locked_options = [
        options[a.target] for a in actions if a.type == "reinforcement" and a.target in options
    ]
    contradictions += [f"locked_reinforcements:{v}" for v in lending_violations(locked_options)]
    return tuple(actions), contradictions, diagnostics, hypothetical


def simulate(
    snapshot: PublicSnapshot,
    locks: ScenarioLocks,
    settings: Settings | None = None,
    max_plans: int | None = None,
) -> Recommendation:
    """Manual mode on the same engine: locked scenario, without and with complements."""
    settings = settings or Settings.default()
    assert_product_backend(settings.backend)
    try:
        start, end, hours = resolve_horizon(snapshot, settings.profile, locks)
    except HorizonError as error:
        return _recommendation(
            status="INFEASIBLE",
            mode="manual",
            snapshot=snapshot,
            settings=settings,
            reasons=[error.code],
            diagnostics=[str(error)],
            bundle=None,
            locks=locks,
        )
    validity = snapshot.as_of + timedelta(
        minutes=int(settings.profile["recommendation_validity_minutes"])
    )
    actions, contradictions, diagnostics, hypothetical = locked_actions(
        snapshot, locks, start, end, validity
    )
    departing = frozenset(a.target for a in actions if a.type != "reinforcement")
    gaps, assumed = _data_gaps(snapshot, settings.profile, start, hours, departing)
    diagnostics = [*diagnostics, *assumed]
    if gaps:
        return _recommendation(
            status="INSUFFICIENT_DATA",
            mode="manual",
            snapshot=snapshot,
            settings=settings,
            reasons=["abstention_data_insufficient"],
            diagnostics=gaps + diagnostics,
            bundle=None,
            locks=locks,
        )
    if contradictions:
        return _recommendation(
            status="INFEASIBLE",
            mode="manual",
            snapshot=snapshot,
            settings=settings,
            reasons=["contradictory_or_impossible_scenario"],
            diagnostics=contradictions + diagnostics,
            bundle=None,
            locks=locks,
        )
    excluded_stays = frozenset(a.target for a in actions if a.type != "reinforcement")
    excluded_options = frozenset(
        lock.option_id for lock in locks.locks if isinstance(lock, LockedReinforcement)
    )
    config = _config(settings, start, hours)
    baseline_plan = make_plan(snapshot, "manual", (), "pratique habituelle")
    if locks.search_complements:
        plans, report = enumerate_plans(
            snapshot,
            settings.profile,
            start,
            end,
            validity,
            "manual",
            actions,
            excluded_stays,
            excluded_options,
            limit=max_plans,
        )
    else:
        plans = [
            make_plan(
                snapshot,
                "manual",
                actions,
                "scénario verrouillé seul",
                tuple(a.action_id for a in actions),
            )
        ]
        report = SearchReport(
            enumerated=1,
            evaluated=1,
            limit=1,
            complete=True,
            filter_rules=("complement search disabled by user",),
            rejected={},
        )
    baseline = settings.backend.forecast(snapshot, baseline_plan, config)
    evaluations = [
        _with_onset(settings.backend.forecast(snapshot, p, config), baseline) for p in plans
    ]
    locked_ids = [a.action_id for a in actions]
    for e in evaluations:  # T18: locks identical in every complement
        kept = [a for a in e.plan.actions if a.action_id in locked_ids]
        if [a.model_dump() for a in kept] != [a.model_dump() for a in actions]:
            raise AssertionError(f"locked decision altered in {e.plan.plan_id}")
    locked = evaluations[0]
    bundle = _bundle(
        snapshot, settings, start, end, hours, [baseline, *evaluations], report, "manual"
    )
    if not locked.admissible:
        return _recommendation(
            status="INFEASIBLE",
            mode="manual",
            snapshot=snapshot,
            settings=settings,
            reasons=["locked_scenario_violates_constraints"],
            diagnostics=[*locked.violations, *diagnostics],
            bundle=bundle,
            baseline=baseline,
            locked=locked,
            locks=locks,
        )
    chosen = select(evaluations, settings.objective)
    tolerance = float(
        next(t for t in settings.objective["tiers"] if t["rank"] == 1)["equivalence_tolerance"]
    )
    reasons = _explain(chosen, baseline, tolerance)
    if not report.complete:
        reasons.append(f"search incomplete: {report.evaluated}/{report.enumerated} plans evaluated")
    if hypothetical:
        return _recommendation(
            status="HYPOTHETICAL_ONLY",
            mode="manual",
            snapshot=snapshot,
            settings=settings,
            reasons=["conditional_simulation_of_hypothesis_not_executable", *reasons],
            diagnostics=diagnostics,
            bundle=bundle,
            baseline=baseline,
            primary=chosen,
            locked=locked,
            locks=locks,
            approvable=False,
        )
    status = "NO_ACTION_PREFERRED" if chosen is locked else "RECOMMENDATION_READY"
    lead = (
        "no_complement_improves_locked_scenario"
        if chosen is locked
        else "complements_to_locked_scenario_require_human_approval"
    )
    return _recommendation(
        status=status,
        mode="manual",
        snapshot=snapshot,
        settings=settings,
        reasons=[lead, *reasons],
        diagnostics=diagnostics,
        bundle=bundle,
        baseline=baseline,
        primary=chosen,
        locked=locked,
        locks=locks,
        approvable=True,
    )


# --------------------------------------------------------------------------- review


@dataclass
class ReviewStore:
    results: dict[str, ReviewResult] = field(default_factory=dict)
    ledger: ResourceLedger = field(default_factory=ResourceLedger)


def _request_fingerprint(recommendation: Recommendation, decision: str) -> str:
    return sha(
        {
            "recommendation_id": recommendation.recommendation_id,
            "snapshot": recommendation.snapshot_fingerprint,
            "decision": decision,
        }
    )


def _primary(recommendation: Recommendation) -> PlanEvaluation | None:
    if recommendation.bundle is None or not recommendation.primary_plan_id:
        return None
    return next(
        e
        for e in recommendation.bundle.evaluations
        if e.plan.plan_id == recommendation.primary_plan_id
    )


def _approval_blockers(
    recommendation: Recommendation, current_snapshot: PublicSnapshot, now: datetime
) -> tuple[str, list[str], bool]:
    """(outcome, reasons, recompute). Same revalidation for auto and manual plans (F01)."""
    if not recommendation.approvable:
        return "REFUSED", [f"not_approvable:{recommendation.status}"], False
    if now >= recommendation.valid_until:
        return "INVALIDATED", ["recommendation_expired"], True
    primary = _primary(recommendation)
    errors = list(plan_precondition_errors(current_snapshot, primary.plan)) if primary else []
    if current_snapshot.fingerprint != recommendation.snapshot_fingerprint:
        if primary is not None:
            for a in primary.plan.actions:
                if a.type in {"coordinate_discharge", "locked_discharge", "locked_extension"}:
                    errors += revalidate_discharge(current_snapshot, a.target)
        return "INVALIDATED", ["new_information_since_recommendation", *dict.fromkeys(errors)], True
    if errors:
        return "REFUSED", [f"precondition_unmet:{e}" for e in errors], True
    return "APPROVED_IN_DEMO", [], False


def _reservation_requests(
    plan_actions: tuple[ActionSpec, ...], snapshot: PublicSnapshot
) -> list[tuple[str, str, str, int | None]]:
    start = snapshot.as_of
    transport, _ = team_capacity(snapshot.teams, "transport", start, 24)
    options = {o.option_id: o for o in snapshot.reinforcements}
    requests: list[tuple[str, str, str, int | None]] = []
    for a in plan_actions:
        if a.type == "reinforcement":
            requests.append((a.target, a.window_start.isoformat(), a.idempotency_key, 1))
            option = options.get(a.target)
            if option is not None and option.source == "shared_unit" and option.lending_unit:
                # F02 across requests: loans from one lender share its spare staff per hour.
                spare = None
                if option.lending_unit_scheduled is not None and (
                    option.lending_unit_minimum is not None
                ):
                    spare = max(0, option.lending_unit_scheduled - option.lending_unit_minimum)
                h = option.start
                while h < option.end:
                    requests.append(
                        (
                            f"lend:{option.lending_unit}:{option.skill}",
                            h.isoformat(),
                            f"{a.idempotency_key}:{h.isoformat()}",
                            spare,
                        )
                    )
                    h += timedelta(hours=1)
        elif "transport_team" in a.resources:
            h = hour_index(start, a.window_start)
            cap = transport[h] if 0 <= h < len(transport) else 0
            requests.append(("transport", a.window_start.isoformat(), a.idempotency_key, cap))
    return requests


def review(
    recommendation: Recommendation,
    decision: str,
    current_snapshot: PublicSnapshot,
    now: datetime,
    idempotency_key: str,
    store: ReviewStore,
) -> ReviewResult:
    """Demo review. Never transmits anything to a hospital system.

    F04: the idempotency key is bound to the request content. Same key + same content returns
    the historical receipt (replayed=True) with its validity re-evaluated now; same key +
    different content raises IdempotencyConflict. F03: reservations are all-or-nothing.
    """
    now = utc(now)
    fingerprint = _request_fingerprint(recommendation, decision)
    if idempotency_key in store.results:
        stored = store.results[idempotency_key]
        if stored.request_fingerprint != fingerprint:
            raise IdempotencyConflict(
                f"idempotency key {idempotency_key!r} already used for another request "
                f"({stored.decision} on {stored.recommendation_id})"
            )
        if stored.outcome == "APPROVED_IN_DEMO":
            outcome_now, why, _ = _approval_blockers(recommendation, current_snapshot, now)
            validity = (
                "still_valid" if outcome_now == "APPROVED_IN_DEMO" else "no_longer_valid:"
                + ",".join(why)
            )
        else:
            validity = "not_applicable"
        return stored.model_copy(update={"replayed": True, "current_validity": validity})
    reasons: list[str] = []
    outcome = {"approve": "APPROVED_IN_DEMO", "reject": "REJECTED", "modify": "MODIFY_REQUESTED"}[
        decision
    ]
    recompute = False
    reservations: list[str] = []
    if decision == "approve":
        outcome, reasons, recompute = _approval_blockers(recommendation, current_snapshot, now)
        primary = _primary(recommendation)
        if outcome == "APPROVED_IN_DEMO" and primary is not None:
            requests = _reservation_requests(primary.plan.actions, current_snapshot)
            ok, details = store.ledger.reserve_all(requests)
            if ok:
                reservations = details
            else:
                outcome = "REFUSED"
                reasons = [f"reservation_refused:{d}" for d in details if d.endswith(
                    ("capacity_exhausted", "capacity_unknown", "other_resource"))]
    result = ReviewResult(
        review_id="rev-" + sha({"key": idempotency_key, "request": fingerprint})[:16],
        recommendation_id=recommendation.recommendation_id,
        decision=decision,  # type: ignore[arg-type]
        outcome=outcome,  # type: ignore[arg-type]
        reasons=tuple(reasons),
        recompute_required=recompute,
        lifecycle={
            "request": "created_in_demo" if outcome == "APPROVED_IN_DEMO" else "none",
            "approval": outcome.lower(),
            "reservation": "local_demo_ledger_only" if reservations else "none",
            "execution": "not_executed_no_external_system",
            "result": "not_observed",
        },
        reservations=tuple(reservations),
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        at=now,
    )
    store.results[idempotency_key] = result
    return result
