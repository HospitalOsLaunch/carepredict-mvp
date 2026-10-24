"""Live-state failure modes: receipt clocks, atomic claims, ambiguity and shadow isolation."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hospitalos.hybrid.demo import pathway_request
from hospitalos.hybrid.journal import reconstruct
from hospitalos.hybrid.live_models import (
    Availability,
    LivePolicy,
    ObservationBatch,
    PlanningOptions,
)
from hospitalos.hybrid.live_store import LiveStore
from hospitalos.hybrid.live_workflow import LiveWorkflow, Reconciliation
from hospitalos.hybrid.models import Bed, Discharge, FactEvent, Patient, ResourcePool
from hospitalos.hybrid.shadow import demo, summarize
from services.api.hybrid_app import create_app

BASE = pathway_request()
AT = BASE.at
OPTIONS = PlanningOptions(assumptions=BASE.assumptions, scenarios=4)


def policy(*, shadow: bool = False) -> LivePolicy:
    return LivePolicy(
        hospital_id=BASE.hospital_id,
        unit_id="medicine",
        sources=("fictional_feed",),
        mode="shadow" if shadow else "sandbox",
    )


def batch(
    seconds: int = 0, *, transport: int | None = 1, cleaning: int | None = 1
) -> ObservationBatch:
    at = AT + timedelta(seconds=seconds)
    facts = tuple(
        e.fact.model_copy(update={"available": transport})
        if isinstance(e.fact, ResourcePool) and e.fact.resource == "transport"
        else e.fact
        for e in BASE.events
    )
    return ObservationBatch(
        batch_id=f"batch-{seconds}-{transport}-{cleaning}",
        hospital_id=BASE.hospital_id,
        source="fictional_feed",
        manifest_version=1,
        expected_entities=BASE.expected_entities,
        events=tuple(
            FactEvent(
                hospital_id=BASE.hospital_id,
                event_id=f"obs-{seconds}:{f.kind}:{f.id}",
                source="fictional_feed",
                event_time=at,
                available_at=at,
                fact=f,
            )
            for f in facts
        ),
        availability=(
            Availability(
                resource="staffed",
                target_id="medicine",
                available=0,
                source="fictional_feed",
                observed_at=at,
                evidence_ref=f"staff-{seconds}",
            ),
            Availability(
                resource="cleaning",
                target_id="medicine",
                available=cleaning,
                source="fictional_feed",
                observed_at=at,
                evidence_ref=f"clean-{seconds}",
            ),
            Availability(
                resource="transport",
                target_id="transport",
                available=transport,
                source="fictional_feed",
                observed_at=at,
                evidence_ref=f"transport-{seconds}",
            ),
            Availability(
                resource="downstream",
                target_id="smr",
                available=1,
                source="fictional_feed",
                observed_at=at,
                evidence_ref=f"smr-{seconds}",
            ),
        ),
    )


@pytest.fixture
def sandbox() -> Iterator[LiveStore]:
    store = LiveStore(policy())
    store.ingest(batch(), AT)
    yield store
    store.close()


@pytest.fixture
def shadow() -> Iterator[LiveStore]:
    store = LiveStore(policy(shadow=True))
    store.ingest(batch(), AT)
    yield store
    store.close()


def sent(store: LiveStore) -> tuple[LiveWorkflow, str]:
    workflow = LiveWorkflow(store)
    key = workflow.propose(AT, OPTIONS)
    workflow.approve(key, AT, "operator")
    command = workflow.dispatch(key, AT)
    assert command.external_execution is False
    return workflow, key


def test_shadow_demo_has_known_denominators_and_no_gain_claim() -> None:
    result = demo()
    assert result["episodes"] == 2 and result["blocked_episodes"] == 1
    assert result["planner_decisions"] == {"recommend": 1}
    assert result["commands_emitted"] == 0
    assert result["causal_effect_established"] is False


def test_shadow_cannot_construct_workflow_or_mutate_command_tables(shadow: LiveStore) -> None:
    episode = shadow.record_shadow(AT, OPTIONS)
    assert episode.assessment.plan is not None
    assert episode.assessment.plan.selected.kind == "request_transport"
    with pytest.raises(ValueError, match="Shadow mode"):
        LiveWorkflow(shadow)
    for table in ("live_proposals", "live_holds", "live_transitions"):
        assert shadow.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_receipt_heartbeat_does_not_refresh_observations(shadow: LiveStore) -> None:
    at = AT + timedelta(seconds=121)
    heartbeat = batch(121).model_copy(update={"events": (), "availability": ()})
    shadow.ingest(heartbeat, at)
    episode = shadow.record_shadow(at, OPTIONS)
    assert episode.assessment.plan is None
    assert "stale_confirmation:transport:transport" in episode.assessment.gate_reasons
    assert episode.assessment.snapshot.received_at_by_source["fictional_feed"] == at.isoformat()


def test_unknown_and_zero_are_distinct_and_no_cleaner_is_inferred(shadow: LiveStore) -> None:
    at = AT + timedelta(seconds=1)
    shadow.ingest(batch(1, transport=0), at)
    episode = shadow.record_shadow(at, OPTIONS)
    assert not episode.assessment.gate_reasons
    assert episode.assessment.plan is not None
    assert episode.assessment.plan.selected.kind == "no_op"
    at += timedelta(seconds=1)
    shadow.ingest(batch(2, cleaning=None), at)
    assert (
        "unknown_availability:cleaning:medicine" in shadow.record_shadow(at).assessment.gate_reasons
    )


def test_busy_cleaners_are_not_projected_as_free(shadow: LiveStore) -> None:
    at = AT + timedelta(seconds=1)
    shadow.ingest(batch(1, cleaning=0), at)
    snapshot = shadow.snapshot(at)
    assert snapshot.state.units[0].cleaning_teams == 1
    projected = LiveStore.planning_events(snapshot)
    projected_unit = next(e.fact for e in projected if e.fact.kind == "unit")
    assert projected_unit.cleaning_teams == 0
    assert snapshot.state.units[0].cleaning_teams == 1  # Raw observation remains intact.


def test_duplicate_receipt_and_retransmitted_events_do_not_refresh(shadow: LiveStore) -> None:
    assert shadow.ingest(batch(), AT + timedelta(seconds=30)) is False
    retransmission = batch().model_copy(update={"batch_id": "retransmission", "availability": ()})
    shadow.ingest(retransmission, AT + timedelta(seconds=60))
    snapshot = shadow.snapshot(AT + timedelta(seconds=121))
    assert all(e.available_at == AT and e.event_time == AT for e in snapshot.events)
    assert "stale_confirmation:staffed:medicine" in snapshot.issues
    assert shadow.ingest(batch(), AT) is False  # Restarted replay is also idempotent.


def test_ingestion_rolls_back_partial_fact_batch_on_error(shadow: LiveStore) -> None:
    before = shadow.snapshot(AT)
    bad = batch(10)
    bad = bad.model_copy(
        update={
            "availability": (
                bad.availability[0].model_copy(update={"observed_at": AT + timedelta(days=1)}),
            )
        }
    )
    with pytest.raises(ValueError, match="Future availability"):
        shadow.ingest(bad, AT + timedelta(seconds=10))
    after = shadow.snapshot(AT)
    assert after.state.fingerprint == before.state.fingerprint
    assert shadow.db.execute("SELECT COUNT(*) FROM live_batches").fetchone()[0] == 1


def test_late_correction_does_not_leak_into_past_and_episode_is_immutable(
    shadow: LiveStore,
) -> None:
    episode = shadow.record_shadow(AT, OPTIONS)
    transport = next(e for e in batch().events if e.fact.id == "transport")
    correction = transport.model_copy(
        update={
            "version": 2,
            "fact": transport.fact.model_copy(update={"available": 0}),
        }
    )
    later = batch(10, transport=0).model_copy(update={"events": (correction,)})
    shadow.ingest(later, AT + timedelta(seconds=10))
    all_events = tuple(
        FactEvent.model_validate_json(r[0])
        for r in shadow.db.execute("SELECT body FROM live_facts")
    )
    past = reconstruct(all_events, BASE.hospital_id, AT, BASE.expected_entities)
    assert next(p.available for p in past.pools if p.id == "transport") == 1
    current = shadow.snapshot(AT + timedelta(seconds=10))
    assert next(p.available for p in current.state.pools if p.id == "transport") == 0
    assert shadow.episode(episode.episode_id) == episode
    with pytest.raises(ValueError, match="monotonic"):
        shadow.snapshot(AT)


def test_manifest_change_requires_version_and_retired_facts_are_audited(shadow: LiveStore) -> None:
    next_batch = batch(1)
    manifest = tuple(k for k in next_batch.expected_entities if k != "patient:incoming")
    next_batch = next_batch.model_copy(
        update={
            "expected_entities": manifest,
            "events": tuple(e for e in next_batch.events if e.fact.id != "incoming"),
        }
    )
    with pytest.raises(ValueError, match="new version"):
        shadow.ingest(next_batch, AT + timedelta(seconds=1))
    shadow.ingest(next_batch.model_copy(update={"manifest_version": 2}), AT + timedelta(seconds=1))
    snapshot = shadow.snapshot(AT + timedelta(seconds=1))
    assert not snapshot.issues
    assert all(p.id != "incoming" for p in snapshot.state.patients)
    assert any("incoming" in r[0] for r in shadow.db.execute("SELECT original FROM live_facts"))


@pytest.mark.parametrize("change", ["hospital", "source", "unit", "version", "identity"])
def test_untrusted_scope_or_identity_is_rejected(shadow: LiveStore, change: str) -> None:
    incoming = batch(1)
    if change == "hospital":
        incoming = incoming.model_copy(update={"hospital_id": "elsewhere"})
    elif change == "source":
        incoming = incoming.model_copy(update={"source": "unconfigured"})
    elif change == "unit":
        event = incoming.events[0]
        incoming = incoming.model_copy(
            update={
                "events": (
                    event.model_copy(
                        update={
                            "fact": event.fact.model_copy(update={"id": "other-unit"}),
                        }
                    ),
                )
            }
        )
    elif change == "version":
        incoming = incoming.model_copy(update={"manifest_version": 5})
    else:
        incoming = incoming.model_copy(
            update={
                "events": (
                    incoming.events[0].model_copy(update={"event_id": batch().events[0].event_id}),
                )
            }
        )
    with pytest.raises(ValueError):
        shadow.ingest(incoming, AT + timedelta(seconds=1))


def test_same_timestamp_conflicting_resource_reports_block(shadow: LiveStore) -> None:
    conflict = (
        batch().availability[2].model_copy(update={"available": 0, "evidence_ref": "conflict"})
    )
    shadow.ingest(
        batch(1).model_copy(update={"events": (), "availability": (conflict,)}),
        AT + timedelta(seconds=1),
    )
    assert (
        "conflicting_confirmation:transport:transport"
        in shadow.snapshot(AT + timedelta(seconds=1)).issues
    )
    shadow.ingest(batch(2), AT + timedelta(seconds=2))
    assert not shadow.snapshot(AT + timedelta(seconds=2)).issues


def test_approval_accepts_fresh_same_value_confirmation(sandbox: LiveStore) -> None:
    workflow = LiveWorkflow(sandbox)
    before = sandbox.snapshot(AT)
    key = workflow.propose(AT, OPTIONS)
    sandbox.ingest(batch(10), AT + timedelta(seconds=10))
    after = sandbox.snapshot(AT + timedelta(seconds=10))
    assert before.state.fingerprint != after.state.fingerprint
    assert before.semantic_fingerprint == after.semantic_fingerprint
    workflow.approve(key, AT + timedelta(seconds=10), "operator")
    assert workflow.history(key)[-1][0] == "approved"


def test_changed_capacity_blocks_before_approval(sandbox: LiveStore) -> None:
    workflow = LiveWorkflow(sandbox)
    key = workflow.propose(AT, OPTIONS)
    sandbox.ingest(batch(1, transport=0), AT + timedelta(seconds=1))
    with pytest.raises(ValueError, match="changed"):
        workflow.approve(key, AT + timedelta(seconds=1), "operator")
    assert sandbox.db.execute("SELECT COUNT(*) FROM live_holds").fetchone()[0] == 0


def test_changed_capacity_blocks_again_at_dispatch(sandbox: LiveStore) -> None:
    workflow = LiveWorkflow(sandbox)
    key = workflow.propose(AT, OPTIONS)
    workflow.approve(key, AT, "operator")
    sandbox.ingest(batch(1, transport=0), AT + timedelta(seconds=1))
    with pytest.raises(ValueError, match="changed"):
        workflow.dispatch(key, AT + timedelta(seconds=1))
    assert workflow.history(key)[-1][0] == "approved"
    workflow.dismiss(key, AT + timedelta(seconds=1), "operator", "resource changed")
    assert sandbox.db.execute("SELECT COUNT(*) FROM live_holds").fetchone()[0] == 0


def test_two_connections_cannot_claim_the_same_unit_concurrently(tmp_path: Path) -> None:
    path = str(tmp_path / "race.sqlite")
    one, two = LiveStore(policy(), path), LiveStore(policy(), path)
    try:
        one.ingest(batch(), AT)
        first, second = LiveWorkflow(one), LiveWorkflow(two)
        keys = first.propose(AT, OPTIONS), second.propose(AT, OPTIONS)

        def approve(pair: tuple[LiveWorkflow, str]) -> bool:
            try:
                pair[0].approve(pair[1], AT, "operator")
                return True
            except ValueError:
                return False

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(approve, ((first, keys[0]), (second, keys[1]))))
        assert sorted(outcomes) == [False, True]
        assert one.db.execute("SELECT COUNT(DISTINCT proposal) FROM live_holds").fetchone()[0] == 1
    finally:
        one.close()
        two.close()


def test_unsent_holds_expire_but_approval_cannot_be_reused(sandbox: LiveStore) -> None:
    workflow = LiveWorkflow(sandbox)
    key = workflow.propose(AT, OPTIONS)
    workflow.approve(key, AT, "operator")
    later = AT + timedelta(seconds=61)
    with pytest.raises(ValueError, match="holds expired"):
        workflow.dispatch(key, later)
    sandbox.snapshot(later)  # Commit expiration even after failed dispatch rolled back.
    assert sandbox.db.execute("SELECT COUNT(*) FROM live_holds").fetchone()[0] == 0
    new = workflow.propose(later, OPTIONS)
    workflow.approve(new, later, "operator")


def test_proposal_ttl_is_stricter_than_legacy_plan(sandbox: LiveStore) -> None:
    workflow = LiveWorkflow(sandbox)
    key = workflow.propose(AT, OPTIONS)
    sandbox.ingest(batch(120), AT + timedelta(seconds=120))
    with pytest.raises(ValueError, match="Proposal expired"):
        workflow.approve(key, AT + timedelta(seconds=120), "operator")


def test_acknowledgement_is_not_completion_or_release(sandbox: LiveStore) -> None:
    workflow, key = sent(sandbox)
    workflow.acknowledge(key, AT, "adapter", "receipt-1")
    assert sandbox.db.execute("SELECT COUNT(*) FROM live_holds").fetchone()[0] == 4
    with pytest.raises(ValueError, match="already dispatched"):
        workflow.dispatch(key, AT)
    with pytest.raises(ValueError, match="reconciliation"):
        workflow.dismiss(key, AT, "operator", "cancel")
    with pytest.raises(ValueError, match="No actionable"):
        workflow.propose(AT, OPTIONS)


def test_unknown_survives_restart_and_ttl_without_retry(tmp_path: Path) -> None:
    path = str(tmp_path / "durable.sqlite")
    store = LiveStore(policy(), path)
    store.ingest(batch(), AT)
    workflow, key = sent(store)
    workflow.mark_unknown(key, AT, "adapter", "timeout")
    store.close()
    store = LiveStore(policy(), path)
    try:
        later = AT + timedelta(minutes=20)
        snapshot = store.snapshot(later)
        assert next(r for r in snapshot.resources if r.key == "transport:transport").held == 1
        workflow = LiveWorkflow(store)
        assert workflow.history(key)[-1][0] == "unknown"
        with pytest.raises(ValueError, match="already dispatched"):
            workflow.dispatch(key, later)
    finally:
        store.close()


def evidence(key: str, at: datetime, *, completed: bool = False) -> Reconciliation:
    return Reconciliation(
        command_id=key,
        outcome="completed" if completed else "not_executed",
        source="fictional_feed",
        observed_at=at,
        evidence_ref="command-bound-proof",
        resource_accounting_confirmed=True,
    )


def test_reconciliation_needs_post_dispatch_facts_and_resource_evidence(sandbox: LiveStore) -> None:
    workflow, key = sent(sandbox)
    later = AT + timedelta(seconds=10)
    with pytest.raises(ValueError, match="facts must be observed"):
        workflow.reconcile(evidence(key, later), later, "operator")
    sandbox.ingest(batch(10).model_copy(update={"availability": ()}), later)
    with pytest.raises(ValueError, match="confirmations must be observed"):
        workflow.reconcile(evidence(key, later), later, "operator")
    sandbox.ingest(batch(11), AT + timedelta(seconds=11))
    workflow.reconcile(
        evidence(key, AT + timedelta(seconds=11)), AT + timedelta(seconds=11), "operator"
    )
    assert workflow.history(key)[-1][0] == "not_executed"
    assert sandbox.db.execute("SELECT COUNT(*) FROM live_holds").fetchone()[0] == 0
    with pytest.raises(ValueError, match="already dispatched"):
        workflow.dispatch(key, AT + timedelta(seconds=11))


def test_transport_requested_does_not_prove_completion(sandbox: LiveStore) -> None:
    workflow, key = sent(sandbox)
    fresh = batch(10)
    fresh = fresh.model_copy(
        update={
            "events": tuple(
                e.model_copy(
                    update={"fact": e.fact.model_copy(update={"transport_requested": True})}
                )
                if isinstance(e.fact, Discharge)
                else e
                for e in fresh.events
            )
        }
    )
    sandbox.ingest(fresh, AT + timedelta(seconds=10))
    with pytest.raises(ValueError, match="does not support"):
        workflow.reconcile(
            evidence(key, AT + timedelta(seconds=10), completed=True),
            AT + timedelta(seconds=10),
            "operator",
        )
    assert sandbox.db.execute("SELECT COUNT(*) FROM live_holds").fetchone()[0] == 4


def test_completed_departure_and_fresh_accounting_release_claims(sandbox: LiveStore) -> None:
    workflow, key = sent(sandbox)
    fresh = batch(10)
    events: list[FactEvent] = []
    for event in fresh.events:
        fact = event.fact
        if isinstance(fact, Patient) and fact.id == "outgoing":
            fact = fact.model_copy(update={"status": "departed", "bed_id": None})
        elif isinstance(fact, Bed):
            fact = fact.model_copy(update={"state": "dirty", "occupant": None})
        elif isinstance(fact, Discharge):
            fact = fact.model_copy(update={"transport_requested": True})
        events.append(event.model_copy(update={"fact": fact}))
    fresh = fresh.model_copy(
        update={
            "events": tuple(events),
            "availability": tuple(
                o.model_copy(update={"available": 1}) if o.resource == "staffed" else o
                for o in fresh.availability
            ),
        }
    )
    later = AT + timedelta(seconds=10)
    sandbox.ingest(fresh, later)
    workflow.reconcile(evidence(key, later, completed=True), later, "operator")
    assert workflow.history(key)[-1][0] == "completed"
    assert sandbox.db.execute("SELECT COUNT(*) FROM live_holds").fetchone()[0] == 0


def test_persisted_policy_cannot_be_reopened_in_sandbox(tmp_path: Path) -> None:
    path = str(tmp_path / "shadow.sqlite")
    LiveStore(policy(shadow=True), path).close()
    with pytest.raises(ValueError, match="immutable"):
        LiveStore(policy(), path)


def test_api_uses_server_clock_and_exposes_no_live_mutation(shadow: LiveStore) -> None:
    with TestClient(create_app(shadow, clock=lambda: AT + timedelta(seconds=121))) as client:
        response = client.get("/hybrid/live")
        assert response.status_code == 200
        assert "stale_confirmation:transport:transport" in response.json()["issues"]
        response = client.post("/hybrid/shadow", json=OPTIONS.model_dump(mode="json"))
        assert response.status_code == 200 and response.json()["assessment"]["plan"] is None
        assert client.post("/hybrid/shadow", json={"at": AT.isoformat()}).status_code == 422
        for route in ("ingest", "approve", "dispatch", "execute", "reconcile"):
            assert client.post(f"/hybrid/{route}", json={}).status_code == 404


def test_api_refuses_sandbox_and_summary_cannot_claim_benefit(sandbox: LiveStore) -> None:
    with pytest.raises(ValueError, match="shadow-mode"):
        create_app(sandbox)
    assert summarize(())["episodes"] == 0


@pytest.mark.parametrize("reservation", [False, True])
def test_cleaning_and_bed_reservation_require_observed_completion(reservation: bool) -> None:
    from hospitalos.hybrid.demo import demo_request
    from hospitalos.hybrid.models import Unit

    request = demo_request()
    if reservation:
        facts = (
            Unit(id="medicine", staffed_beds=2, cleaning_teams=1),
            Bed(id="bed-a", unit_id="medicine", state="clean", capabilities=("oxygen",)),
            Bed(id="bed-z", unit_id="medicine", state="clean"),
            Patient(
                id="general",
                status="waiting",
                compatible_units=("medicine",),
                waiting_since=AT - timedelta(hours=2),
                priority=2,
            ),
            Patient(
                id="special",
                status="waiting",
                compatible_units=("medicine",),
                requirements=("oxygen",),
                waiting_since=AT - timedelta(hours=1),
            ),
        )
        initial_events = tuple(
            FactEvent(
                hospital_id=BASE.hospital_id,
                event_id=f"initial:{f.kind}:{f.id}",
                source="fictional_feed",
                event_time=AT,
                available_at=AT,
                fact=f,
            )
            for f in facts
        )
    else:
        initial_events = request.events
    initial = ObservationBatch(
        batch_id="initial",
        hospital_id=BASE.hospital_id,
        source="fictional_feed",
        manifest_version=1,
        expected_entities=tuple(f"{e.fact.kind}:{e.fact.id}" for e in initial_events),
        events=initial_events,
        availability=(
            Availability(
                resource="staffed",
                target_id="medicine",
                available=2,
                source="fictional_feed",
                observed_at=AT,
                evidence_ref="staff-free",
            ),
            Availability(
                resource="cleaning",
                target_id="medicine",
                available=1,
                source="fictional_feed",
                observed_at=AT,
                evidence_ref="cleaner-free",
            ),
        ),
    )
    store = LiveStore(policy())
    try:
        store.ingest(initial, AT)
        workflow = LiveWorkflow(store)
        key = workflow.propose(AT, OPTIONS)
        workflow.approve(key, AT, "operator")
        command = workflow.dispatch(key, AT)
        assert command.action["kind"] == ("reserve_bed" if reservation else "prioritize_cleaning")
        later = AT + timedelta(seconds=10)
        refreshed: list[FactEvent] = []
        for event in initial.events:
            fact = event.fact
            if isinstance(fact, Bed) and fact.id == command.action["bed_id"]:
                fact = fact.model_copy(
                    update={"state": "clean", "reserved_for": command.action["patient_id"]}
                )
            refreshed.append(
                FactEvent(
                    hospital_id=BASE.hospital_id,
                    event_id=f"finished:{fact.kind}:{fact.id}",
                    source="fictional_feed",
                    event_time=later,
                    available_at=later,
                    fact=fact,
                )
            )
        finished = initial.model_copy(
            update={
                "batch_id": "finished",
                "events": tuple(refreshed),
                "availability": tuple(
                    o.model_copy(
                        update={
                            "observed_at": later,
                            "available": 1
                            if reservation and o.resource == "staffed"
                            else o.available,
                        }
                    )
                    for o in initial.availability
                ),
            }
        )
        store.ingest(finished, later)
        workflow.reconcile(evidence(key, later, completed=True), later, "operator")
        assert workflow.history(key)[-1][0] == "completed"
        assert store.db.execute("SELECT COUNT(*) FROM live_holds").fetchone()[0] == 0
    finally:
        store.close()
