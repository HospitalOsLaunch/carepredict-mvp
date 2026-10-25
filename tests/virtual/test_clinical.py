"""Physical constraints independent of the web application or recommendation policy."""

from datetime import UTC, datetime, timedelta

from hospitalos.virtual.clinical import CarePatient, ClinicalEngine
from hospitalos.virtual.config import HospitalConfig


def engine() -> ClinicalEngine:
    return ClinicalEngine(
        HospitalConfig(
            hospital_id="H1",
            name="Test",
            beds=6,
            staffed_beds=6,
            initially_occupied=1,
            oxygen_beds=(2, 5),
        ),
        7,
        lambda frame: None,
        epoch=datetime(2026, 10, 25, 0, tzinfo=UTC),
    )


def test_reclosing_bed_cannot_be_undone_by_previous_expiry() -> None:
    e = engine()
    e.close_bed("geriatrie-G06", e.now + timedelta(seconds=60), "first")
    e.reopen_bed("geriatrie-G06")
    e.close_bed("geriatrie-G06", e.now + timedelta(seconds=180), "second")
    e.advance(61)
    assert not e.beds["geriatrie-G06"].opened
    e.advance(120)
    assert e.beds["geriatrie-G06"].opened
    assert not e.closures


def test_capacity_reduction_preserves_occupants_and_blocks_installation() -> None:
    e = engine()
    occupied = {b.id: b.occupant for b in e.beds.values() if b.occupant}
    e.set_capacity(0, e.now + timedelta(seconds=120), "absence")
    assert not e._reserve("geriatrie-P-W001", "geriatrie-G06", coordinated=True)
    e.advance(61)
    assert {b.id: b.occupant for b in e.beds.values() if b.occupant} == occupied
    e.set_capacity(2, e.now + timedelta(seconds=180), "new shift")
    e.advance(61)
    assert e.staffed_capacity == 2
    e.advance(120)
    assert e.staffed_capacity == 6


def test_protected_capacity_is_for_named_admission_only() -> None:
    e = engine()
    e.declared_capacity = 2
    e.holds["geriatrie-G06"] = "planned"
    p = CarePatient("planned", 0, compatible_units=("geriatrie",))
    e.patients[p.id] = p
    assert not e._reserve("geriatrie-P-W001", "geriatrie-G04", coordinated=True)
    assert not e._reserve(p.id, "geriatrie-G04", coordinated=True)
    assert e._reserve(p.id, "geriatrie-G06", coordinated=True)
    assert not e.holds
    e.advance(121)
    assert p.status == "admitted"


def test_authorization_alone_does_not_discharge_patient() -> None:
    e = engine()
    p = e.patients["geriatrie-P-I000"]
    assert isinstance(p, CarePatient)
    p.cleared = True
    p.transport_required = True
    p.downstream_required = True
    e._try_depart(p)
    assert (p.id, "departure") not in e.service_requests
    e.request_service(p.id, "documents")
    e.advance(1201)
    assert p.documents_ready
    assert p.status == "admitted"
    assert not p.transport_ready
    assert not p.downstream_ready


def test_programmed_admissions_use_paris_after_fallback() -> None:
    e = engine()
    scheduled = e.schedule(e.now, e.now + timedelta(hours=24))
    assert scheduled[0]["at"] == "2026-10-25T07:00:00+00:00"
    e.advance(7 * 3600)
    assert scheduled[0]["id"] in e.completed_admissions
    patient = e.patients[scheduled[0]["id"]]
    assert isinstance(patient, CarePatient)
    assert patient.programmed


def test_pending_receiving_consent_blocks_autonomous_placement() -> None:
    e = engine()
    p = CarePatient("transfer", 0, compatible_units=("geriatrie",))
    e.patients[p.id] = p
    e.pending_placements.add(p.id)
    assert not e._reserve(p.id, "geriatrie-G06")
    assert e._reserve(p.id, "geriatrie-G06", coordinated=True)


def test_shift_models_exclude_future_validation_targets() -> None:
    from hospitalos.virtual.history import History

    start = datetime(2026, 9, 1, tzinfo=UTC)
    models = []
    for perturb in (False, True):
        history = History(":memory:", 18)
        try:
            rows = [
                (
                    (start + timedelta(hours=i)).isoformat(),
                    (17 if perturb and i > 504 else 6 + i % 8),
                    i % 3,
                    4,
                )
                for i in range(673)
            ]
            with history.db:
                history.db.executemany("INSERT INTO observations VALUES (?, ?, ?, ?)", rows)
            history.fit()
            summary = history.summary()
            models.append(summary["model"]["shift_models"])
            assert [f["horizon_hours"] for f in summary["shift_forecasts"]] == [8, 24]
            for forecast in summary["shift_forecasts"]:
                assert 0 <= forecast["lower"] <= forecast["upper"] <= 18
                assert forecast["train_target_until"] < forecast["validation_target_from"]
        finally:
            history.close()
    for original, changed in zip(*models, strict=True):
        assert original["coefficients"] == changed["coefficients"]


def test_transport_confirmation_cannot_make_another_patient_ready() -> None:
    from hospitalos.hybrid.models import discharge_blockers
    from hospitalos.virtual.clinical import CareFrame
    from hospitalos.virtual.feed import VirtualFeed

    e = engine()
    patients = []
    for index, ready in enumerate((True, False)):
        bed = e.beds[f"geriatrie-G0{index + 3}"]
        patient = CarePatient(
            f"test-{index}",
            0,
            status="admitted",
            bed=bed.id,
            compatible_units=("geriatrie",),
            cleared=True,
            discharge_planned=True,
            documents_ready=True,
            transport_required=True,
            transport_requested=True,
            transport_ready=ready,
        )
        bed.occupant = patient.id
        patients.append(patient)
    feed = VirtualFeed(lambda: e.now, e.config, epoch=e.epoch)
    try:
        feed.receive(CareFrame(e.now, tuple(e.beds.values()), tuple(patients), 1, 6, ()))
        snapshot = feed.store.snapshot(e.now)
        assert not snapshot.issues
        state = snapshot.state
        assert not discharge_blockers(state, state.patients[0])
        assert "transport_unavailable" in discharge_blockers(state, state.patients[1])
    finally:
        feed.store.close()
