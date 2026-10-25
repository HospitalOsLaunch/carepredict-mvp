"""Executable integration, causality-boundary and concurrency checks for the demo slice."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hospitalos.simulator.engine import HospitalSimulation, TruthEvent
from hospitalos.simulator.evaluation import evaluate
from hospitalos.simulator.session import ControlRequest, DecisionRequest, DemoSession
from services.api.hybrid_app import app as shadow_app
from services.api.simulator_app import create_app


@pytest.fixture
def session() -> Any:
    value = DemoSession(monotonic=lambda: 0)
    yield value
    value.close()


def control(session: DemoSession, operation: str, seconds: int = 300) -> Any:
    view = session.view()
    return session.control(
        ControlRequest.model_validate(
            {
                "run_id": view.run_id,
                "request_id": f"control-{view.revision}",
                "revision": view.revision,
                "operation": operation,
                "seconds": seconds,
            }
        )
    )


def decision(session: DemoSession, accept: bool = True) -> DecisionRequest:
    session.assess()
    view = session.view()
    assert view.can_apply and view.episode is not None
    plan = view.episode.assessment.plan
    assert plan is not None and plan.selected.bed_id == "G02"
    return DecisionRequest(
        run_id=view.run_id,
        request_id="choice-1",
        revision=view.revision,
        plan_id=plan.plan_id,
        snapshot_fingerprint=view.snapshot.semantic_fingerprint,
        accept=accept,
    )


def test_real_planner_action_delayed_observations_and_installation(session: DemoSession) -> None:
    request = decision(session)
    view = session.decide(request)
    assert view.commands[0].status == "accepted"
    assert session.engine.priority is None  # Acceptance is not physical execution.
    control(session, "advance", 30)
    assert session.view().commands[0].status == "executed"
    control(session, "advance", 60)
    assert session.engine.cleaning_bed == "G02"
    # Finish is not yet visible in the declared SI at its exact physical boundary.
    while not any(e.kind == "cleaning_finished" for e in session.engine.journal):
        session.engine.advance(1)
    assert session.engine.beds["G02"].hygiene == "ready"
    visible = session.view().snapshot.state
    assert next(b for b in visible.beds if b.id == "G02").state == "dirty"
    control(session, "advance", 180)
    visible = session.view().snapshot.state
    bed = next(b for b in visible.beds if b.id == "G02")
    patient = next(p for p in visible.patients if p.id == "P-G01")
    assert bed.occupant == patient.id and bed.reserved_for is None
    assert patient.status == "admitted" and patient.bed_id == bed.id


def test_duplicate_command_and_distinct_concurrent_command(session: DemoSession) -> None:
    request = decision(session)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(session.decide, (request, request)))
    assert len(results[-1].commands) == 1
    assert sum(e.kind == "coordination_requested" for e in session.engine.journal) == 1
    other = request.model_copy(update={"request_id": "choice-2"})
    with pytest.raises(ValueError, match="revision_changed"):
        session.decide(other)
    with pytest.raises(ValueError, match="request_identity_conflict"):
        session.decide(request.model_copy(update={"accept": False}))


def test_two_distinct_writes_from_same_revision_have_one_winner(session: DemoSession) -> None:
    request = decision(session)

    def attempt(item: DecisionRequest) -> str:
        try:
            session.decide(item)
            return "ok"
        except ValueError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(attempt, (request, request.model_copy(update={"request_id": "other"})))
        )
    assert sorted(results) == ["conflict", "ok"]


def test_refusal_has_processing_cost_and_no_priority_effect(session: DemoSession) -> None:
    session.decide(decision(session, False))
    control(session, "advance", 90)
    assert session.view().commands[0].status == "refused"
    assert session.engine.cleaning_bed == "G01"
    assert not any(e.kind == "cleaning_prioritized" for e in session.engine.journal)
    result = control(session, "finish").evaluation
    assert result is not None and result.coordination_tasks == 1


def test_execution_rechecks_truth_after_acceptance(session: DemoSession) -> None:
    session.decide(decision(session))
    session.engine.beds["G02"].opened = False
    control(session, "advance", 30)
    assert session.view().commands[0].status == "failed"
    assert session.engine.priority is None


@pytest.mark.parametrize("change", ["expire", "state", "run"])
def test_stale_or_cross_run_action_rejected(session: DemoSession, change: str) -> None:
    request = decision(session)
    if change == "expire":
        session.engine.advance(120)
    elif change == "state":
        session.engine.beds["G02"].opened = False
        session.engine.advance(60)
    else:
        control(session, "reset")
    with pytest.raises(ValueError):
        session.decide(request)
    assert not session.commands


def test_cleaning_priority_is_non_preemptive_and_does_not_change_duration() -> None:
    base = HospitalSimulation(9, lambda frame: None)
    treated = HospitalSimulation(9, lambda frame: None)
    base.advance(120)
    treated.advance(120)
    outcomes: list[str] = []
    treated.command("prioritize_cleaning", "G02", None, True, outcomes.append)
    base.advance(3600)
    treated.advance(3600)
    for world in (base, treated):
        starts = [e for e in world.journal if e.kind == "cleaning_started"]
        assert starts[0].bed == "G01" and starts[0].second == 120
    assert [e for e in base.journal if e.kind == "cleaning_finished" and e.bed == "G01"] == [
        e for e in treated.journal if e.kind == "cleaning_finished" and e.bed == "G01"
    ]
    assert outcomes == ["executed"]


def test_common_primitives_and_reproducible_reset(session: DemoSession) -> None:
    control(session, "advance", 3600)
    first = tuple(session.engine.journal)
    control(session, "reset")
    control(session, "advance", 3600)
    assert tuple(session.engine.journal) == first
    other = HospitalSimulation(session.seed, lambda frame: None)
    for bed in ("G01", "G02"):
        assert other._duration("cleaning", bed, (900, 1200, 1500)) == session.engine._duration(
            "cleaning", bed, (900, 1200, 1500)
        )


def test_disconnect_preserves_old_observations_and_reconnects(session: DemoSession) -> None:
    before = session.view().snapshot.events
    control(session, "disconnect")
    control(session, "advance", 720)  # An arrival happened while the source was unavailable.
    stale = session.view()
    assert stale.snapshot.events == before
    assert stale.snapshot.issues
    session.assess()
    assert not session.view().can_apply
    control(session, "reconnect")
    control(session, "advance", 120)
    fresh = session.view()
    assert not fresh.snapshot.issues
    assert "P-G02" in {p.id for p in fresh.snapshot.state.patients}


def test_manual_and_accelerated_time_share_one_clock() -> None:
    wall = [0.0]
    session = DemoSession(monotonic=lambda: wall[0])
    try:
        control(session, "play")
        wall[0] = 2
        assert session.view().now == session.engine.now
        assert session.engine.second == 150
        control(session, "pause")
        wall[0] = 300
        assert session.view().now == session.engine.now and session.engine.second == 150
        control(session, "advance", 60)
        assert session.engine.second == 210
    finally:
        session.close()


def test_control_retry_does_not_advance_twice(session: DemoSession) -> None:
    view = session.view()
    request = ControlRequest(
        run_id=view.run_id,
        revision=view.revision,
        request_id="step",
        operation="advance",
        seconds=300,
    )
    first = session.control(request)
    second = session.control(request)
    assert first.now == second.now and first.revision == second.revision


def test_manual_steps_stop_at_horizon_and_close_episode(session: DemoSession) -> None:
    for _ in range(3):
        result = control(session, "advance", 3600)
    assert session.engine.second == 10800
    assert result.completed and result.evaluation is not None
    with pytest.raises(ValueError, match="run_completed"):
        session.assess()


def test_reservation_command_preserves_coordinator_queue_and_rechecks_installation() -> None:
    world = HospitalSimulation(7, lambda frame: None)
    world.beds["G02"].hygiene = "ready"
    statuses: list[tuple[str, float]] = []
    record = lambda status: statuses.append((status, world.second))  # noqa: E731
    world.command("reserve_bed", "G02", "P-G01", True, record)
    world.command("prioritize_cleaning", "G01", None, False, record)
    world.command("prioritize_cleaning", "G01", None, False, record)
    world.advance(30)
    assert world.beds["G02"].reserved_for == "P-G01"
    assert world.coordinator_free == 90
    assert not world._reserve("P-G01", "G02")
    world.beds["G02"].opened = False
    world.advance(60)
    assert statuses == [("executed", 30), ("refused", 60), ("refused", 90)]
    assert world.beds["G02"].reserved_for is None
    assert world.patients["P-G01"].status == "waiting"
    assert any(e.kind == "installation_failed" for e in world.journal)


def test_observations_do_not_expose_future_or_truth_and_results_require_finish(
    session: DemoSession,
) -> None:
    data = session.view().model_dump_json()
    for secret in ("P-G02", "t_true", "journal", "cleaning_duration", "seed", "evaluation_metrics"):
        assert secret not in data
    assert session.view().evaluation is None
    control(session, "advance", 3600)
    control(session, "advance", 3600)
    result = control(session, "finish")
    assert result.evaluation is not None
    assert result.evaluation.patients_total == 3
    assert result.evaluation.departed == 1
    assert result.evaluation.admitted_at_end == 2
    assert result.evaluation.waiting_at_end == 0
    with pytest.raises(ValueError, match="run_completed"):
        control(session, "advance")


def test_notator_integrates_unfinished_waiting_and_rejects_corruption() -> None:
    events = [
        TruthEvent(0, "initial_waiting", "P1"),
        TruthEvent(0, "initial_waiting", "P2"),
        TruthEvent(3600, "installed", "P1", "B1"),
    ]
    result = evaluate(events, 10800)
    assert result.waiting_patient_minutes == 240
    assert result.waiting_at_end == 1
    with pytest.raises(ValueError, match="duplicate"):
        evaluate([events[0], events[0]], 10800)
    with pytest.raises(ValueError, match="double_occupancy"):
        evaluate([*events, TruthEvent(3700, "installed", "P2", "B1")], 10800)
    with pytest.raises(ValueError, match="invalid_event_time"):
        evaluate([events[0], replace(events[1], second=-1)], 10800)


def test_gateway_contract_origin_and_shadow_routes(session: DemoSession) -> None:
    with TestClient(create_app(session)) as client:
        view = client.post("/demo/evaluate", json={}).json()
        assert view["can_apply"]
        request = {
            "run_id": view["run_id"],
            "revision": view["revision"],
            "request_id": "api-action",
            "plan_id": view["episode"]["assessment"]["plan"]["plan_id"],
            "snapshot_fingerprint": view["snapshot"]["semantic_fingerprint"],
            "accept": True,
        }
        assert (
            client.post("/demo/decision", json={**request, "action": "invented"}).status_code == 422
        )
        assert (
            client.post(
                "/demo/decision", json=request, headers={"origin": "https://external.test"}
            ).status_code
            == 403
        )
        assert not session.commands
        assert client.post("/demo/decision", json=request).status_code == 200
        assert client.post("/demo/decision", json=request).status_code == 200
        assert len(client.get("/demo/session").json()["commands"]) == 1
        assert client.get("/hybrid/live").json()["mode"] == "shadow"
        episode = client.post("/hybrid/shadow", json={}).json()
        assert episode["commands_emitted"] == 0
        assert client.get("/demo/truth").status_code == 404
        assert "t_true" not in json.dumps(episode)
    with TestClient(shadow_app) as client:
        assert client.post("/demo/decision", json={}).status_code == 404
        assert client.post("/hybrid/execute", json={}).status_code == 404
