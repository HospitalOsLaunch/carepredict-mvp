"""One-hospital scoping, real-time continuity, DST, and persisted learning provenance."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from hospitalos.virtual.campus import CampusFleet
from hospitalos.virtual.history import History
from hospitalos.virtual.runtime import Decision
from services.api.virtual_app import create_app


@pytest.fixture(scope="module")
def campus(tmp_path_factory: pytest.TempPathFactory) -> Iterator[CampusFleet]:
    now = datetime(2026, 10, 25, 0, 59, tzinfo=UTC)
    fleet = CampusFleet(tmp_path_factory.mktemp("campus"), clock=lambda: now)
    yield fleet
    fleet.close()


def test_single_hospital_four_scoped_units_and_observed_history(campus: CampusFleet) -> None:
    # Explicit client lifespan is omitted: this shared fixture owns runtime cleanup.
    client = TestClient(create_app(campus, start_worker=False))
    catalog = client.get("/product/hospitals").json()
    assert [h["id"] for h in catalog["hospitals"]] == ["H1"]
    assert len(catalog["hospitals"][0]["units"]) == 4
    overview = client.get("/product/hospitals/H1/overview").json()
    assert sum(u["capacity"] for u in overview["units"]) == 78
    assert overview["timezone"] == "Europe/Paris"
    patients = [p for unit in campus.units.values() for p in unit.engine.patients]
    beds = [b for unit in campus.units.values() for b in unit.engine.beds]
    assert len(patients) == len(set(patients))
    assert len(beds) == len(set(beds))
    assert client.get("/product/hospitals/H1/unit").status_code == 404
    assert client.get("/product/hospitals/H1/units/missing/history").status_code == 404
    history = client.get("/product/hospitals/H1/units/geriatrie/history").json()
    assert history["samples"] >= 672
    model = history["model"]
    assert model["training_pairs"] >= 479
    assert model["validation_pairs"] == 168
    assert model["train_until"] < model["validation_from"] <= model["validation_until"]
    assert datetime.fromisoformat(model["validation_until"]) <= campus.clock()
    assert len(model["data_sha256"]) == 64
    assert 0 <= history["forecast"]["occupied"] <= 18
    export = client.get("/product/hospitals/H1/units/geriatrie/history/export")
    assert export.status_code == 200
    assert len(export.text.strip().splitlines()) == history["samples"] + 1
    request = Decision(
        hospital_id="H1",
        unit_id="medecine",
        run_id="wrong",
        request_id="cross-unit",
        revision=0,
        plan_id="p",
        snapshot_fingerprint="s",
        accept=True,
    )
    assert (
        client.post(
            "/product/hospitals/H1/units/geriatrie/decisions", json=request.model_dump()
        ).status_code
        == 409
    )
    assert all(not unit.records for unit in campus.units.values())


def test_paris_fallback_advances_two_minutes_not_backwards(campus: CampusFleet) -> None:
    before = campus.get("geriatrie").engine.now
    after = before + timedelta(minutes=2)
    campus.clock = lambda: after
    campus.sync()
    assert not campus.errors
    for unit in campus.units.values():
        assert unit.engine.now == after
        assert unit.clock_rate == 1
        assert unit.engine.now - before == timedelta(minutes=2)
    paris = ZoneInfo("Europe/Paris")
    assert before.astimezone(paris).utcoffset() == timedelta(hours=2)
    assert after.astimezone(paris).utcoffset() == timedelta(hours=1)


def test_history_artifact_is_frozen_when_new_observations_arrive(campus: CampusFleet) -> None:
    for key, history in campus.histories.items():
        original = dict(history.summary()["model"])
        history.fit()
        assert history.summary()["model"] == original
        assert history.summary()["samples"] == len(history.export_rows())
        assert len(campus.units[key].engine.patients) < 120


def test_campus_restart_replays_elapsed_time_without_retraining(tmp_path: Path) -> None:
    now = datetime(2026, 10, 25, 12, tzinfo=UTC)
    first = CampusFleet(tmp_path, clock=lambda: now)
    first_model = first.histories["medecine"].summary()["model"]
    run_ids = {key: unit.run_id for key, unit in first.units.items()}
    first.close()
    now += timedelta(minutes=65)
    second = CampusFleet(tmp_path, clock=lambda: now)
    try:
        assert second.histories["medecine"].summary()["model"] == first_model
        assert {key: unit.run_id for key, unit in second.units.items()} == run_ids
        assert all(unit.engine.now == now for unit in second.units.values())
        history = second.histories["medecine"].summary()
        assert datetime.fromisoformat(history["until"]) > datetime.fromisoformat(
            first_model["validation_until"]
        )
    finally:
        second.close()


def test_training_requires_sufficient_observations() -> None:
    history = History(":memory:", 18)
    try:
        with pytest.raises(ValueError, match="insufficient"):
            history.fit()
    finally:
        history.close()
