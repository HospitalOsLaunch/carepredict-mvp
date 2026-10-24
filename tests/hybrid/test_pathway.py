"""Hand-calculated path oracles, resource contention and forged-log rejection."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from pydantic import ValidationError

from hospitalos.hybrid.demo import pathway_request
from hospitalos.hybrid.models import (
    Action,
    Bed,
    Discharge,
    Fact,
    FactEvent,
    Patient,
    ResourcePool,
    Unit,
    action_errors,
)
from hospitalos.hybrid.planning import PlanRequest, plan
from hospitalos.hybrid.scoring import score
from hospitalos.hybrid.simulation import Assumptions, Trajectory, Transition, simulate
from hospitalos.hybrid.workflow import Workflow


def with_facts(request: PlanRequest, *facts: Fact) -> PlanRequest:
    entries = {f"{e.fact.kind}:{e.fact.id}": e for e in request.events}
    for fact in facts:
        key = f"{fact.kind}:{fact.id}"
        entries[key] = FactEvent(
            hospital_id=request.hospital_id,
            event_id=f"fixture:{key}",
            source="fictional_feed",
            event_time=request.at,
            available_at=request.at,
            fact=fact,
        )
    return request.model_copy(
        update={"events": tuple(entries.values()), "expected_entities": tuple(sorted(entries))}
    )


def no_op_trace(request: PlanRequest) -> Trajectory:
    return simulate(
        request.state(),
        Action(kind="no_op"),
        request.assumptions,
        seed=7,
        scenario=0,
        horizon_minutes=request.horizon_minutes,
    )


def transport_action() -> Action:
    return Action(kind="request_transport", patient_id="outgoing", bed_id="bed-1")


def two_units(*, places: int = 2, teams: int = 1) -> PlanRequest:
    request = pathway_request()
    d = request.state().discharges[0]
    return with_facts(
        request,
        d.model_copy(update={"transport_requested": True}),
        Unit(id="ward-2", staffed_beds=1, cleaning_teams=1),
        Bed(id="bed-2", unit_id="ward-2", state="occupied", occupant="outgoing-2"),
        Patient(
            id="outgoing-2",
            status="admitted",
            bed_id="bed-2",
            compatible_units=("ward-2",),
            waiting_since=request.at,
            medically_cleared=True,
            downstream_confirmed=True,
        ),
        Patient(
            id="incoming-2",
            status="waiting",
            compatible_units=("ward-2",),
            waiting_since=request.at,
        ),
        d.model_copy(update={"id": "outgoing-2", "transport_requested": True}),
        ResourcePool(
            id="smr", resource="downstream", unit_ids=("medicine", "ward-2"), available=places
        ),
        ResourcePool(
            id="transport", resource="transport", unit_ids=("medicine", "ward-2"), available=teams
        ),
    )


def test_release_transport_clean_allocate_has_hand_calculated_times() -> None:
    request = pathway_request()
    proposal = plan(request)
    assert proposal.selected == transport_action()
    assert proposal.discharge_readiness[0].stage == "transport_to_request"
    assert proposal.service_status == "served_in_all_sampled_scenarios"
    state = request.state()
    trace = simulate(
        state, proposal.selected, request.assumptions, seed=7, scenario=0, horizon_minutes=360
    )
    assert [(e.kind, e.minute) for e in trace.events] == [
        ("request_transport", 0),
        ("departure_ready", 30),
        ("downstream_reserve", 30),
        ("transport_start", 30),
        ("transport_depart", 75),
        ("depart", 75),
        ("clean_start", 75),
        ("clean_end", 105),
        ("transport_end", 105),
        ("admit", 105),
    ]
    assert score(state, trace).waiting_patient_minutes == 105
    assert score(state, trace).violations == ()
    baseline = no_op_trace(request)
    assert baseline.events == ()
    assert score(state, baseline).waiting_patient_minutes == 360


@pytest.mark.parametrize(
    "field,value",
    [
        ("documents_ready", None),
        ("documents_ready", False),
        ("escort_required", None),
        ("escort_required", True),
        ("downstream_required", None),
        ("transport_requested", None),
    ],
)
def test_missing_confirmation_never_becomes_a_departure(field: str, value: bool | None) -> None:
    request = pathway_request()
    changes: dict[str, object] = {field: value}
    if field == "downstream_required":
        changes["downstream_pool_id"] = None
    d = Discharge.model_validate({**request.state().discharges[0].model_dump(), **changes})
    request = with_facts(request, d)
    result = plan(request)
    assert result.selected.kind == "no_op"
    assert result.discharge_readiness[0].blockers
    assert result.service_status == "unserved_in_some_sampled_scenarios"
    assert not any(e.kind == "depart" for e in no_op_trace(request).events)


def test_old_two_booleans_do_not_fabricate_logistics() -> None:
    request = pathway_request()
    events = tuple(e for e in request.events if e.fact.kind != "discharge")
    request = request.model_copy(
        update={
            "events": events,
            "expected_entities": tuple(f"{e.fact.kind}:{e.fact.id}" for e in events),
        }
    )
    assert "discharge_logistics_missing" in plan(request).discharge_readiness[0].blockers
    assert no_op_trace(request).events == ()


def test_explicit_not_applicable_allows_home_departure_without_transport_or_aval() -> None:
    request = pathway_request()
    d = Discharge(
        id="outgoing",
        documents_ready=True,
        escort_required=False,
        transport_required=False,
        downstream_required=False,
    )
    patient = next(p for p in request.state().patients if p.id == "outgoing")
    request = with_facts(request, d, patient.model_copy(update={"downstream_confirmed": None}))
    trace = no_op_trace(request)
    assert next(e.minute for e in trace.events if e.kind == "depart") == 30
    assert next(e.minute for e in trace.events if e.kind == "admit") == 60
    assert not any(
        e.kind.startswith("transport") or e.kind == "downstream_reserve" for e in trace.events
    )
    assert score(request.state(), trace).violations == ()


def test_shared_transport_serializes_two_units() -> None:
    request = two_units()
    trace = no_op_trace(request)
    assert [(e.patient_id, e.minute) for e in trace.events if e.kind == "transport_start"] == [
        ("outgoing", 30),
        ("outgoing-2", 105),
    ]
    assert [e.minute for e in trace.events if e.kind == "admit"] == [105, 180]
    assert score(request.state(), trace).waiting_patient_minutes == 285
    assert score(request.state(), trace).violations == ()


def test_finite_aval_is_consumed_once_and_not_released_after_transport() -> None:
    request = two_units(places=1)
    trace = no_op_trace(request)
    assert len([e for e in trace.events if e.kind == "downstream_reserve"]) == 1
    assert len([e for e in trace.events if e.kind == "depart"]) == 1
    assert score(request.state(), trace).waiting_at_end == 1
    assert score(request.state(), trace).violations == ()


def test_simultaneous_departures_respect_shared_pools() -> None:
    request = two_units(teams=2)
    trace = no_op_trace(request)
    assert [e.minute for e in trace.events if e.kind == "depart"] == [75, 75]
    assert [e.minute for e in trace.events if e.kind == "admit"] == [105, 105]
    assert score(request.state(), trace).violations == ()


@pytest.mark.parametrize("resource", ["transport", "smr"])
def test_absent_resource_blocks_release_without_infeasibility_claim(resource: str) -> None:
    request = pathway_request()
    pool = next(p for p in request.state().pools if p.id == resource)
    request = with_facts(request, pool.model_copy(update={"available": 0}))
    result = plan(request)
    assert result.decision == "no_change"
    assert result.service_status == "unserved_in_some_sampled_scenarios"
    assert no_op_trace(request).events == ()


def test_combined_cleaner_and_staff_shortage_does_not_admit_after_departure() -> None:
    request = two_units()
    request = with_facts(
        request,
        Unit(id="medicine", staffed_beds=0, cleaning_teams=0),
        Unit(id="ward-2", staffed_beds=0, cleaning_teams=0),
    )
    trace = no_op_trace(request)
    assert len([e for e in trace.events if e.kind == "depart"]) == 2
    assert not any(e.kind in {"clean_start", "admit"} for e in trace.events)
    assert score(request.state(), trace).violations == ()
    assert len(request.state().warnings) == 2


def test_in_progress_transport_at_horizon_keeps_bed_occupied() -> None:
    request = two_units().model_copy(update={"horizon_minutes": 50})
    trace = no_op_trace(request)
    assert len([e for e in trace.events if e.kind == "transport_start"]) == 1
    assert not any(e.kind in {"depart", "clean_start", "admit"} for e in trace.events)
    assert score(request.state(), trace).waiting_patient_minutes == 100
    assert score(request.state(), trace).violations == ()


def test_future_logistics_correction_does_not_unlock_at_D() -> None:
    request = pathway_request()
    original = next(e for e in request.events if isinstance(e.fact, Discharge))
    assert isinstance(original.fact, Discharge)
    blocked = original.model_copy(
        update={"fact": original.fact.model_copy(update={"documents_ready": False})}
    )
    correction = original.model_copy(
        update={"version": 2, "available_at": request.at + timedelta(minutes=10)}
    )
    request = request.model_copy(
        update={
            "events": tuple(
                blocked if e.event_id == original.event_id else e for e in request.events
            )
            + (correction,)
        }
    )
    assert plan(request).selected.kind == "no_op"
    later = request.model_copy(update={"at": correction.available_at})
    assert plan(later).selected == transport_action()


def test_stale_pool_and_wrong_pool_scope_cause_abstention() -> None:
    request = two_units()
    pool = next(p for p in request.state().pools if p.id == "transport")
    wrong = with_facts(request, pool.model_copy(update={"unit_ids": ("ward-2",)}))
    assert plan(wrong).decision == "abstain"
    events = tuple(
        e.model_copy(
            update={
                "event_time": request.at - timedelta(minutes=61),
                "available_at": request.at - timedelta(minutes=61),
            }
        )
        if e.fact.kind == "pool"
        else e
        for e in request.events
    )
    assert plan(request.model_copy(update={"events": events})).decision == "abstain"


@pytest.mark.parametrize(
    "omitted_kind",
    [
        "departure_ready",
        "downstream_reserve",
        "transport_start",
        "transport_depart",
        "transport_end",
        "clean_end",
    ],
)
def test_scorer_rejects_missing_pathway_step(omitted_kind: str) -> None:
    request = two_units()
    trace = no_op_trace(request)
    forged = replace(trace, events=tuple(e for e in trace.events if e.kind != omitted_kind))
    assert score(request.state(), forged).violations


def test_scorer_rejects_double_consumption_of_aval() -> None:
    roomy = two_units(places=2, teams=2)
    constrained = two_units(places=1, teams=2)
    assert "downstream_capacity" in score(constrained.state(), no_op_trace(roomy)).violations


def test_scorer_rejects_concurrent_transport_over_capacity() -> None:
    parallel = two_units(teams=2)
    constrained = two_units(teams=1)
    assert "transport_capacity" in score(constrained.state(), no_op_trace(parallel)).violations


def test_scorer_rejects_wrong_resource_and_zero_duration_transport() -> None:
    request = two_units()
    trace = no_op_trace(request)
    events = tuple(
        replace(e, resource_id="wrong-pool") if e.kind == "transport_start" else e
        for e in trace.events
    )
    assert (
        "invalid_transport_start"
        in score(request.state(), replace(trace, events=events)).violations
    )
    forged = Trajectory(
        360,
        (
            Transition(30, "departure_ready", "outgoing", "bed-1"),
            Transition(30, "downstream_reserve", "outgoing", "bed-1", "smr"),
            Transition(30, "transport_start", "outgoing", "bed-1", "transport"),
            Transition(30, "transport_end", "outgoing", "bed-1", "transport"),
        ),
    )
    assert "invalid_transport_end" in score(request.state(), forged).violations


def test_paired_request_does_not_accelerate_preparation_or_service() -> None:
    request = pathway_request()
    already_requested = with_facts(
        request, request.state().discharges[0].model_copy(update={"transport_requested": True})
    )
    assumptions = Assumptions()
    for seed in range(4):
        for scenario in range(12):
            action_trace = simulate(
                request.state(), transport_action(), assumptions, seed=seed, scenario=scenario
            )
            baseline_trace = simulate(
                already_requested.state(),
                Action(kind="no_op"),
                assumptions,
                seed=seed,
                scenario=scenario,
            )
            assert action_trace.events[1:] == baseline_trace.events
            assert score(request.state(), action_trace).violations == ()


def test_resource_stress_matrix_has_no_mechanics_violation() -> None:
    for places, teams in ((0, 1), (1, 1), (2, 0), (2, 1), (2, 2)):
        request = two_units(places=places, teams=teams)
        for seed in range(4):
            for scenario in range(12):
                trace = simulate(
                    request.state(),
                    Action(kind="no_op"),
                    Assumptions(),
                    seed=seed,
                    scenario=scenario,
                )
                assert score(request.state(), trace).violations == ()


def test_transport_request_rechecks_logistics_and_does_not_mutate_facts() -> None:
    request = pathway_request()
    proposal = plan(request)
    workflow = Workflow()
    workflow.propose(proposal)
    workflow.approve(proposal.plan_id, request.state(), request.at, "fictional_operator")
    changed = with_facts(
        request, request.state().discharges[0].model_copy(update={"documents_ready": False})
    )
    with pytest.raises(ValueError, match="changed"):
        workflow.dispatch(proposal.plan_id, changed.state(), request.at)
    command = workflow.dispatch(proposal.plan_id, request.state(), request.at)
    assert '"external_execution": false' in command
    assert request.state().discharges[0].transport_requested is False
    with pytest.raises(ValueError):
        workflow.dispatch(proposal.plan_id, request.state(), request.at)
    workflow.close()


def test_duplicate_unknown_or_nonmedical_transport_request_is_rejected() -> None:
    request = pathway_request()
    for requested in (True, None):
        changed = with_facts(
            request,
            request.state().discharges[0].model_copy(update={"transport_requested": requested}),
        )
        assert action_errors(changed.state(), transport_action())
    p = next(p for p in request.state().patients if p.id == "outgoing")
    changed = with_facts(request, p.model_copy(update={"medically_cleared": False}))
    assert action_errors(changed.state(), transport_action())


def test_strict_confirmation_and_versioned_contract_reject_implicit_migration() -> None:
    payload = pathway_request().events[0].model_dump()
    payload["schema_version"] = "HYBRID_MVP_1"
    with pytest.raises(ValidationError):
        FactEvent.model_validate(payload)
    with pytest.raises(ValidationError):
        Discharge(id="outgoing", documents_ready="yes")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Discharge(id="outgoing", transport_required=False, transport_pool_id="transport")
