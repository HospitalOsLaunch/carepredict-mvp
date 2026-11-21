"""Compare complete four-hour programs using one common public hospital trajectory.

Small scopes are enumerated exactly. The full product catalogue uses a bounded search
in both resource-first and patient-first order. A separately requested plan is always
evaluated on its own, regardless of whether the automatic search visited it.
"""

from __future__ import annotations

import hashlib
import itertools
from collections.abc import Iterable, Sequence
from functools import lru_cache

import numpy as np

from . import engine
from .contracts import (
    Objective,
    Observation,
    PlanEvaluation,
    PlanMenu,
    PlanMetrics,
    PlanReport,
    PlanSearch,
    ReconstructedPlan,
    Session,
    WardCase,
    WardImpact,
    WardMetrics,
    WardState,
)
from .joint_physics import JointResult, simulate_batch, simulate_joint
from .plan_catalogue import Catalogue, catalogue, conflicts, reconcile_noon_intake
from .projection import reconstruct

Ids = tuple[str, ...]
OBJECTIVES: tuple[Objective, ...] = ("transfer_queue", "bed_wait", "uncovered_care")
EXACT_SCOPE = 12


def _identity(context: str, ids: Ids, ward_id: str | None = None) -> str:
    scope = (f"unit:{ward_id}",) if ward_id is not None else ()
    encoded = "\x00".join(
        (engine.plan_version(), context, engine.cases()[context].public_sha, *scope, *ids)
    )
    return "plan-" + hashlib.sha256(encoded.encode()).hexdigest()[:28]


def _check_ids(c: Catalogue, ids: Ids) -> None:
    if len(ids) != len(set(ids)) or any(k not in c.items for k in ids):
        raise ValueError("Action dupliquée ou absente du catalogue de cet établissement.")


def metrics(result: JointResult, catalogue: Catalogue) -> PlanMetrics:
    counts = result.metrics.sum(axis=0)
    return PlanMetrics(
        transfer_queue=float(engine.queue(result.stocks).sum()),
        bed_wait_patient_hours=float(counts[0]),
        uncovered_ide_minutes=float(counts[2]),
        uncovered_as_minutes=float(counts[3]),
        transport_used=float(result.transport_used.sum()),
        beds_cleaned=float(result.beds_cleaned.sum()),
        smr_transfers=float(counts[6]),
        open_beds=float(result.capacities.sum()),
        available_beds=float(result.clean_beds.sum()),
        admissions=float(counts[4]),
        discharges=float(counts[5] + counts[6]),
        redirected_patients=float(counts[7]),
        admission_queue_at_16=float(result.stocks[:, 0].sum()),
        named_admissions=sum(
            c.direction == "admission" and result.case_hour[c.id] is not None
            for c in catalogue.cases
        ),
        named_discharges=sum(
            c.direction == "discharge" and result.case_hour[c.id] is not None
            for c in catalogue.cases
        ),
    )


def _public_rolls(c: Catalogue, keys: Sequence[Ids]) -> list[JointResult]:
    return simulate_batch(
        c.data,
        c.data["initial"],
        c.data["drivers"],
        [[c.items[k].action for k in ids] for ids in keys],
        c.kernel,
        known_cases=c.cases,
    )


def ward_index(context: str, ward_id: str) -> int:
    for index in range(len(engine.cases()[context].wards)):
        if ward_id == f"u{index + 1}":
            return index
    raise ValueError("Cette unité n’appartient pas à cet établissement.")


def unit_scope(c: Catalogue, ward: int) -> Ids:
    # A named loan into the unit may require replacement coverage at the donor.
    # A loan out of the unit also affects this unit and its available staff.
    local = [
        item.action for item in c.items.values() if ward in (item.action.ward, item.action.donor)
    ]
    donors = {
        (a.donor, "ide" if a.mode == "loan" else "as")
        for a in local
        if a.ward == ward and a.mode in ("loan", "redeploy")
    }
    support = {
        k
        for k, item in c.items.items()
        if (item.action.ward, "ide" if item.action.mode == "replacement" else item.action.mode)
        in donors
    }
    return tuple(sorted({a.id for a in local} | support))


def ward_state(context: str, ward_id: str) -> WardState:
    ward = ward_index(context, ward_id)
    c = catalogue(context)
    stock = c.data["initial"][ward]
    beds = int(c.data["beds"][ward])
    return WardState(
        context_id=context,
        ward_id=ward_id,
        capacity_beds=beds,
        available_beds=max(0.0, beds - float(stock[1:].sum())),
        admission_queue=float(stock[0]),
        transfer_queue=float(engine.queue(stock)),
        cases=[
            WardCase(
                id=k,
                kind=item.description.kind,
                eligible=item.description.eligible,
                available_hour=item.description.start_hour,
                scheduled_hour=next((p.scheduled_hour for p in c.cases if p.id == k), None)
                if item.description.eligible
                else None,
            )
            for k, item in c.items.items()
            if item.action.ward == ward and item.description.kind in ("admission", "discharge")
        ],
    )


class Evaluator:
    def __init__(self, context: str, ward: int | None = None) -> None:
        self.ward = ward
        self.context = context
        self.ward_id = f"u{ward + 1}" if ward is not None else None
        self.c = catalogue(context)
        self.values: dict[Ids, PlanEvaluation] = {}
        self.simulated = 0

    def evaluate(self, candidates: Iterable[Ids]) -> None:
        pending = []
        for ids in dict.fromkeys(itertools.chain([()], candidates)):
            if ids in self.values:
                continue
            problems = conflicts(self.c, ids)
            value = PlanEvaluation(
                id=_identity(self.context, ids, self.ward_id),
                context_id=self.context,
                ward_id=self.ward_id,
                action_ids=list(ids),
                feasible=not problems,
                conflicts=problems,
                cost_eur=sum(self.c.items[k].description.cost_eur for k in ids),
                metrics=None,
                realized={},
            )
            self.values[ids] = value
            if not problems:
                pending.append(ids)
        for start in range(0, len(pending), 256):
            group = pending[start : start + 256]
            for ids, result in zip(group, _public_rolls(self.c, group), strict=True):
                self.simulated += 1
                value = self.values[ids]
                value.metrics = metrics(result, self.c)
                if self.ward is not None:
                    w = self.ward
                    counts = result.metrics[w]
                    value.ward_metrics = WardMetrics(
                        transfer_queue=float(engine.queue(result.stocks)[w]),
                        bed_wait_patient_hours=float(counts[0]),
                        uncovered_ide_minutes=float(counts[2]),
                        uncovered_as_minutes=float(counts[3]),
                        admissions=float(counts[4]),
                        redirected_patients=float(counts[7]),
                    )
                value.realized = result.realized
                value.case_hours = result.case_hour
                value.access_warnings = access_warnings(value, self.values[()])
                missing = [
                    k
                    for k in ids
                    if self.c.items[k].action.mode in ("admission", "discharge")
                    and result.realized[k] < 1
                ]
                if missing:
                    value.feasible = False
                    value.conflicts = [
                        "À ressources et horaires prévus, réalisation incomplète à 16 h pour "
                        + ", ".join(missing)
                        + ". Ajustez les moyens ou la sélection."
                    ]


def access_warnings(plan: PlanEvaluation, reference: PlanEvaluation) -> list[str]:
    """Protect access when ranking automatic proposals. Manual comparisons preserve tradeoffs."""
    a, b = plan.metrics, reference.metrics
    assert a is not None and b is not None
    messages = []
    if a.admissions < b.admissions - 1e-7:
        messages.append(
            f"Moins d’admissions prévues ({a.admissions:.2f} contre {b.admissions:.2f})."
        )
    if a.redirected_patients > b.redirected_patients + 1e-7:
        messages.append(
            f"Davantage de réorientations prévues ({a.redirected_patients:.2f} "
            f"contre {b.redirected_patients:.2f})."
        )
    wa, wb = plan.ward_metrics, reference.ward_metrics
    if wa is not None and wb is not None:
        if wa.admissions < wb.admissions - 1e-7:
            messages.append("Moins d’admissions prévues dans l’unité.")
        if wa.redirected_patients > wb.redirected_patients + 1e-7:
            messages.append("Davantage de réorientations prévues dans l’unité.")
    missed = [
        k for k, h in reference.case_hours.items() if h is not None and plan.case_hours[k] is None
    ]
    if missed:
        messages.append(
            "Dossiers encore en attente à 16 h, servis dans le planning initial · "
            + ", ".join(missed)
            + "."
        )
    for k, booked in reference.case_hours.items():
        estimated = plan.case_hours[k]
        if booked is not None and estimated is not None and estimated > booked:
            messages.append(
                f"Dossier {k} prévu à {estimated} h, contre {booked} h avec le planning."
            )
    return messages


def _score(plan: PlanEvaluation, objective: Objective) -> tuple[float, int, int, tuple[str, ...]]:
    m = plan.ward_metrics or plan.metrics
    if m is None:
        target = float("inf")
    elif objective == "transfer_queue":
        target = m.transfer_queue
    elif objective == "bed_wait":
        target = m.bed_wait_patient_hours
    else:
        target = m.uncovered_ide_minutes + m.uncovered_as_minutes
    return round(target, 8), plan.cost_eur, len(plan.action_ids), tuple(plan.action_ids)


def _beam(e: Evaluator, scope: Ids) -> None:
    # Alternatives for one named person or team are mutually exclusive by construction.
    groups: dict[str, list[str]] = {}
    for k in scope:
        item = e.c.items[k]
        if item.description.eligible:
            groups.setdefault(item.claim, []).append(k)
    ordered = sorted(
        groups.values(),
        key=lambda g: (
            {
                "replacement": 0,
                "reinforcement": 1,
                "redeployment": 2,
                "beds": 3,
                "transport": 4,
                "cleaning": 5,
                "smr": 6,
                "discharge": 7,
                "admission": 8,
            }[e.c.items[g[0]].description.kind],
            g[0],
        ),
    )
    e.evaluate([(), *((k,) for k in scope), *itertools.combinations(scope, 2)])
    # Include coordinated patient/staff movements even when each intermediate action alone
    # offers no gain. This seed is evaluated, never privileged in the final ranking.
    patient = tuple(k for k in scope if e.c.items[k].description.kind in ("admission", "discharge"))
    shifts = [
        k
        for k in scope
        if e.c.items[k].description.kind in ("reinforcement", "replacement", "redeployment")
    ]
    e.evaluate(
        tuple(sorted(patient + combo))
        for size in range(4)
        for combo in itertools.combinations(shifts, size)
    )
    for order in (ordered, list(reversed(ordered))):
        frontier: set[Ids] = {()}
        for group in order:
            possible = frontier | {
                tuple(sorted((*parent, k))) for parent in frontier for k in group
            }
            e.evaluate(possible)
            live = [ids for ids in sorted(possible) if e.values[ids].metrics is not None]
            frontier = {()}
            for objective in OBJECTIVES:
                ranked = sorted(
                    live,
                    key=lambda ids: (
                        not e.values[ids].feasible,
                        bool(e.values[ids].access_warnings),
                        _score(e.values[ids], objective),
                    ),
                )
                frontier.update(ranked[:6])
                # Keep physically evaluated partial plans whose missing resource appears later.
                hot = sorted(
                    live, key=lambda ids: (_score(e.values[ids], objective)[0], -len(ids), ids)
                )
                frontier.update(hot[:3])
            frontier.update(sorted(live, key=lambda ids: (-len(ids), ids))[:2])


def _best(values: Iterable[PlanEvaluation], objective: Objective) -> list[PlanEvaluation]:
    ranked = sorted(
        (p for p in values if p.feasible and not p.access_warnings and p.metrics is not None),
        key=lambda p: _score(p, objective),
    )
    distinct: list[PlanEvaluation] = []
    seen = set()
    for plan in ranked:
        assert plan.metrics is not None
        local = plan.ward_metrics.model_dump().values() if plan.ward_metrics else ()
        signature = (
            plan.cost_eur,
            *(round(v, 6) for v in (*local, *plan.metrics.model_dump().values())),
        )
        if signature not in seen:
            seen.add(signature)
            distinct.append(plan)
        if len(distinct) == 3:
            break
    return distinct


def with_ward_impacts(c: Catalogue, evaluations: Iterable[PlanEvaluation]) -> None:
    published = {p.id: p for p in evaluations if p.metrics is not None}
    if not published:
        return
    results = _public_rolls(c, [(), *(tuple(p.action_ids) for p in published.values())])
    reference = results[0]
    for plan, result in zip(published.values(), results[1:], strict=True):
        diff = result.metrics - reference.metrics
        queue = engine.queue(result.stocks) - engine.queue(reference.stocks)
        plan.ward_impacts = [
            WardImpact(
                ward_id=f"u{w + 1}",
                transfer_queue=float(queue[w]),
                admissions=float(diff[w, 4]),
                redirected_patients=float(diff[w, 7]),
                care_minutes=float(diff[w, 2] + diff[w, 3]),
                transport_used=float(result.transport_used[w] - reference.transport_used[w]),
                beds_cleaned=float(result.beds_cleaned[w] - reference.beds_cleaned[w]),
                smr_transfers=float(diff[w, 6]),
                available_beds=float(result.clean_beds[w] - reference.clean_beds[w]),
            )
            for w in range(len(queue))
        ]


def trim_recommendations(e: Evaluator) -> None:
    # Test removals against the whole plan. Drop neutral actions and keep jointly necessary pairs.
    visited: set[Ids] = set()
    while True:
        best = {
            tuple(plan.action_ids) for goal in OBJECTIVES for plan in _best(e.values.values(), goal)
        }
        fresh = sorted(best - visited)
        if not fresh:
            return
        visited.update(fresh)
        for ids in fresh:
            e.evaluate(
                tuple(k for k in ids if k not in removed)
                for size in (1, 2)
                for removed in itertools.combinations(ids, size)
            )


@lru_cache(maxsize=24)
def _search(context: str, scope: Ids, ward_id: str | None = None) -> dict[Objective, PlanMenu]:
    e = Evaluator(context, ward_index(context, ward_id) if ward_id is not None else None)
    _check_ids(e.c, scope)
    exact = len(scope) <= EXACT_SCOPE
    if exact:
        e.evaluate(
            combo for n in range(len(scope) + 1) for combo in itertools.combinations(scope, n)
        )
    else:
        _beam(e, scope)
        trim_recommendations(e)
    best_by_goal = {goal: _best(e.values.values(), goal) for goal in OBJECTIVES}
    if ward_id is not None:
        reference = e.values[()]
        for goal, plans in best_by_goal.items():
            threshold = _score(reference, goal)[0]
            best_by_goal[goal] = [p for p in plans if _score(p, goal)[0] < threshold] or [reference]
    with_ward_impacts(e.c, [e.values[()], *(p for plans in best_by_goal.values() for p in plans)])
    state = ward_state(context, ward_id) if ward_id is not None else None
    return {
        goal: PlanMenu(
            context_id=context,
            ward_state=state,
            objective=goal,
            ward_id=ward_id,
            actions=[
                item.description for k, item in e.c.items.items() if ward_id is None or k in scope
            ],
            reference=e.values[()],
            recommendations=best_by_goal[goal],
            search=PlanSearch(
                evaluated=e.simulated,
                complete=exact,
                examined=len(e.values),
                feasible=sum(p.feasible for p in e.values.values()),
                recommendable=sum(p.feasible and not p.access_warnings for p in e.values.values()),
                scope_size=len(scope),
            ),
            scope_ids=list(scope),
            example_action_ids=list(e.c.example) if ward_id is None else [],
            budget_eur=e.c.budget,
        )
        for goal in OBJECTIVES
    }


def menu(context: str, objective: Objective, scope: Sequence[str] | None = None) -> PlanMenu:
    selected = tuple(sorted(catalogue(context).items if scope is None else scope))
    return _search(context, selected)[objective]


def unit_menu(context: str, ward_id: str, objective: Objective) -> PlanMenu:
    scope = unit_scope(catalogue(context), ward_index(context, ward_id))
    return _search(context, scope, ward_id)[objective]


def preview(context: str, action_ids: Sequence[str], ward_id: str | None = None) -> PlanEvaluation:
    ids = tuple(sorted(action_ids))
    ward = ward_index(context, ward_id) if ward_id is not None else None
    e = Evaluator(context, ward)
    if ward is not None and not set(ids).issubset(unit_scope(e.c, ward)):
        raise ValueError("Certaines actions sont hors du périmètre de l’unité.")
    _check_ids(e.c, ids)
    e.evaluate([ids])
    with_ward_impacts(e.c, [e.values[ids]])
    return e.values[ids]


def publish(state: Session, case: engine.Case, now: int) -> None:
    selected, snapshot = state.confirmed_plan, state.plan_snapshot
    if selected is None or snapshot is None or now < case.publication:
        raise ValueError("Le relevé du plan n’est pas encore disponible.")
    # All alternative arms use only their original noon public inputs. One factual branch
    # receives the realized drivers, and only after publication of the context's report.
    c = catalogue(case.context.id)
    chosen = tuple(selected.action_ids)
    alternatives = {p.id: p for p in [selected, snapshot.reference, *snapshot.recommendations]}
    compared = list(alternatives.values())
    predictions = _public_rolls(c, [tuple(p.action_ids) for p in compared])
    tape = engine.arrays(case, "events")
    initial = reconcile_noon_intake(tape["initial"], c.census_admissions, c.direct_arrivals)
    actual = simulate_joint(
        c.data,
        initial,
        tape["drivers"],
        [c.items[k].action for k in chosen],
        c.kernel,
        known_cases=c.cases,
    )
    visible = tape["mask"]
    measured = np.where(visible, actual.stocks, np.nan)
    ward_counts = engine.queue(measured)
    state.observation = Observation(
        sample_hour=16,
        published_hour=now,
        observed_stock=float(ward_counts.sum()) if np.isfinite(ward_counts).all() else None,
        by_ward=[float(v) if np.isfinite(v) else None for v in ward_counts],
        visible_components=int(visible.sum()),
        total_components=int(visible.size),
    )
    corrected = reconstruct(
        np.stack([r.stocks for r in predictions]),
        0,
        measured,
        visible,
        np.stack([r.capacities for r in predictions]),
        now=now,
        published=case.publication,
    )
    # The synthetic full feed includes a complete execution ledger. Other feeds only
    # expose the masked census; their omitted activity is not interpreted as zero.
    full = case.context.feed == "full"
    state.plan_report = PlanReport(
        actual_metrics=metrics(actual, c) if full else None,
        case_hours=actual.case_hour if full else None,
        realized=actual.realized if full else None,
        alternatives=[
            ReconstructedPlan(plan=p, reconstructed_queue=float(engine.queue(stocks).sum()))
            for p, stocks in zip(compared, corrected, strict=True)
            if p.id != selected.id
        ],
    )
