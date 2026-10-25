"""Operational isolation, replay, observation boundary and causal pairing regressions."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hospitalos.virtual.campaign import pair, run
from hospitalos.virtual.config import hospitals
from hospitalos.virtual.engine import VirtualEngine
from hospitalos.virtual.runtime import Decision, HospitalRuntime, VirtualFleet
from services.api.virtual_app import create_app


def decision(unit: HospitalRuntime, accept: bool = True) -> Decision:
    unit.assess(force=True)
    view = unit.view()
    assert view.can_decide and view.episode and view.episode.assessment.plan
    return Decision(
        hospital_id=view.hospital_id,
        run_id=view.run_id,
        request_id="test-request",
        revision=view.revision,
        plan_id=view.episode.assessment.plan.plan_id,
        snapshot_fingerprint=view.snapshot.semantic_fingerprint,
        accept=accept,
        reason="Contrainte locale" if not accept else "",
    )


def test_durable_idempotent_decision_and_physical_replay(tmp_path: Path) -> None:
    path = str(tmp_path / "unit.sqlite")
    unit = HospitalRuntime(hospitals()[0], path=path)
    request = decision(unit)
    unit.decide(request)
    unit.decide(request)
    assert len(unit.records) == 1
    unit.advance(1800, plan=False)
    truth = unit.engine.journal.copy()
    activity = unit.activity
    records = unit.records.copy()
    run_id = unit.run_id
    unit.close()
    restored = HospitalRuntime(hospitals()[0], path=path)
    try:
        assert restored.run_id == run_id
        assert restored.engine.journal == truth
        assert restored.activity == activity
        assert restored.records == records
        restored.decide(request)
        assert len(restored.records) == 1
        with pytest.raises(ValueError, match="identity_conflict"):
            restored.decide(request.model_copy(update={"accept": False, "reason": "autre"}))
    finally:
        restored.close()


def test_hospital_scope_and_revision_are_authoritative() -> None:
    fleet = VirtualFleet()
    try:
        x1, x2 = fleet.get("X1"), fleet.get("X2")
        request = decision(x1)
        with pytest.raises(ValueError, match="mismatch"):
            x2.decide(request)
        with pytest.raises(ValueError, match="changed"):
            x1.decide(request.model_copy(update={"revision": 99}))
        x1.decide(request)
        assert not x2.records
        assert x2.engine.second == hospitals()[1].delivery_seconds
    finally:
        fleet.close()


def test_background_clock_without_clients_and_state_lock(tmp_path: Path) -> None:
    fleet = VirtualFleet(tmp_path, clock_rate=60)
    with pytest.raises(ValueError, match="already_running"):
        VirtualFleet(tmp_path)
    fleet.start()
    before = [u.engine.second for u in fleet.units.values()]
    time.sleep(0.65)
    try:
        assert all(
            u.engine.second > old for u, old in zip(fleet.units.values(), before, strict=True)
        )
    finally:
        fleet.close()
    other = VirtualFleet(tmp_path)
    other.close()


def test_observation_is_delayed_and_feed_is_bounded() -> None:
    u = HospitalRuntime(hospitals()[0])
    try:
        before = u.view().snapshot.semantic_fingerprint
        u.advance(30, plan=False)
        assert u.view().snapshot.semantic_fingerprint == before  # next export not delivered yet
        u.advance(86400, plan=False)
        u.engine.check()
        assert u.activity.departures > 10
        assert u.engine.cleaning_occurrences["G02"] > 1
        assert len(u.view().snapshot.state.patients) < len(u.engine.patients)
    finally:
        u.close()


def test_product_routes_do_not_expose_scenario_controls() -> None:
    fleet = VirtualFleet()
    for u in fleet.units.values():
        u.assess()
    with TestClient(create_app(fleet, start_worker=False)) as client:
        assert len(client.get("/product/hospitals").json()["hospitals"]) == 3
        assert client.get("/demo/session").status_code == 404
        assert client.post("/demo/compare", json={}).status_code == 404
        assert client.get("/product/hospitals/unknown/unit").status_code == 404
        request = decision(fleet.get("X1"))
        assert (
            client.post("/product/hospitals/X2/decisions", json=request.model_dump()).status_code
            == 409
        )
        assert (
            client.post("/product/hospitals/X1/decisions", json=request.model_dump()).status_code
            == 200
        )
        assert client.get("/product/hospitals/X2/unit").json()["decisions"] == []
        assert client.get("/health", headers={"Origin": "https://example.com"}).status_code == 403


def test_regimes_and_capacity_contracts() -> None:
    configs = hospitals()
    engines = [VirtualEngine(c, 7, lambda frame: None) for c in configs]
    for e in engines:
        e.advance(7200)
        e.check()
    assert engines[1].arrival_index > engines[0].arrival_index
    assert configs[2].cleaning_seconds[0] > max(configs[0].cleaning_seconds)
    with pytest.raises(ValueError):
        configs[0].model_validate({**configs[0].model_dump(), "staffed_beds": 2})


def test_paired_neutrality_and_refusal_have_identical_physics() -> None:
    neutral = pair(hospitals()[0], 7, "disabled", 1)
    assert neutral["a0"] == neutral["a1"]
    refusal = pair(hospitals()[0], 7, "refuse", 1)
    assert refusal["waiting_patient_minutes_saved"] == 0
    assert refusal["a0"]["journal"] == [
        e for e in refusal["a1"]["journal"] if e["kind"] != "coordination_requested"
    ]


def test_campaign_resume_and_tamper_detection(tmp_path: Path) -> None:
    config = (hospitals()[0],)
    first = run(tmp_path, seeds=(7,), hours=1, policy="disabled", configs=config)
    assert run(tmp_path, seeds=(7,), hours=1, policy="disabled", configs=config) == first
    path = tmp_path / "hospital-00-seed-7.json"
    assert path.exists()
    path.write_text(path.read_text().replace('"seed": 7', '"seed": 8'))
    with pytest.raises(ValueError):
        run(tmp_path, seeds=(7,), hours=1, policy="disabled", configs=config)


def test_acceptance_is_reproducible_and_measured_separately_from_prediction() -> None:
    first = pair(hospitals()[0], 7, "accept", 1)
    second = pair(hospitals()[0], 7, "accept", 1)
    assert first == second
    assert first["a1"]["commands"]
    assert first["a1"]["solicitation_seconds_requested"] > 0
    assert first["waiting_patient_minutes_saved"] == (
        first["a0"]["evaluation"]["waiting_patient_minutes"]
        - first["a1"]["evaluation"]["waiting_patient_minutes"]
    )
