"""Movement timing, revision replacement, censoring and immutable patient datasets."""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pytest

from hospitalos.synthetic import cohort
from hospitalos.synthetic.config import HospitalConfig
from hospitalos.synthetic.generate import generate
from hospitalos.synthetic.learning import _events
from hospitalos.synthetic.patient_asof import PatientAsOfCursor, PatientRow, replay_patients
from hospitalos.synthetic.patient_learning import (
    TruthStay,
    build_patient_truth,
    patient_target,
    prepare_patient_run,
)
from hospitalos.synthetic.patient_observations import (
    Admission,
    Departure,
    OnlinePatients,
    PatientDelivery,
    Request,
    Transfer,
    observe_patients,
    source_movement,
)
from hospitalos.synthetic.registry import CohortPlan


@pytest.fixture
def config() -> HospitalConfig:
    raw = json.loads(Path("configs/synthetic/hospital_two_poles.json").read_text())
    raw.update(days=7, warmup_days=2)
    return HospitalConfig.model_validate(raw)


def receipt(
    config: HospitalConfig,
    *,
    event: str = "E1",
    hour: float = 1.0,
    available: float | None = None,
    payload: Any = None,
    unit: str | None = None,
    stay: str = "S1",
    order: int = 1,
    version: int = 1,
    **extra: Any,
) -> PatientDelivery:
    unit = unit or config.units[0].unit_id
    clock = hour if available is None else available
    return PatientDelivery(
        delivery_id=f"{event}:v{version}",
        event_id=event,
        stay_id=stay,
        hospital_id=config.hospital_id,
        pole_id=config.unit_poles[unit],
        unit_id=unit,
        event_order=order,
        event_version=version,
        replaces_version=version - 1 if version > 1 else None,
        event_h=hour,
        recorded_h=hour,
        ingested_h=clock,
        available_h=clock,
        payload=payload or Admission(home_unit_id=unit, bed_id=3),
        **extra,
    )


def truth_events(config: HospitalConfig, exit_hour: int | None = 20) -> list[dict[str, Any]]:
    unit = config.units[0].unit_id

    def e(index: int, hour: int, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "event_id": f"{config.hospital_id}:E{index:09d}",
            "h": hour,
            "type": kind,
            "unit_id": unit,
            "pole_id": config.unit_poles[unit],
            "hospital_id": config.hospital_id,
            "stay_id": f"{config.hospital_id}:S000001",
            "payload": payload,
        }

    rows = [
        e(
            0,
            0,
            "DEMANDE_ADMISSION",
            {
                "mode_entree": "urgences",
                "age": 82,
                "isolement": False,
                "oxygene": True,
                "dependance": 4,
            },
        ),
        e(1, 1, "ADMISSION", {"lit": 3, "unite_cible": 0, "heberge": False, "attente_h": 1}),
    ]
    if exit_hour is not None:
        rows.append(e(2, exit_hour, "SORTIE", {"lit": 3, "destination": "domicile"}))
    return rows


def test_closed_projection_minimizes_age_and_excludes_latent_values(config: HospitalConfig) -> None:
    events = truth_events(config)
    events[0]["payload"].update(ready_h=10000, dis_h=10001, future_occupancy=123)
    first = source_movement(events[0], config)
    assert first is not None and isinstance(first.payload, Request)
    assert first.payload.age_band == "75_84"
    assert first.event_h == first.available_h == 1.0
    assert set(first.payload.model_dump()) == {
        "kind",
        "age_band",
        "admission_mode",
        "isolation",
        "oxygen",
    }
    assert "ready_h" not in first.model_dump_json() and '"age"' not in first.model_dump_json()


@pytest.mark.parametrize(
    "field,value",
    [
        ("available_h", 0.0),
        ("event_h", float("nan")),
        ("ingested_h", float("inf")),
        ("event_version", True),
        ("event_version", 0),
        ("replaces_version", 1),
        ("voided", True),
        ("hidden_ready_h", 50),
    ],
)
def test_delivery_contract_rejects_mutations(
    config: HospitalConfig, field: str, value: Any
) -> None:
    raw = receipt(config).model_dump()
    raw[field] = value
    with pytest.raises(ValueError):
        PatientDelivery.model_validate(raw)


def test_patient_appears_only_when_request_or_movement_is_received(config: HospitalConfig) -> None:
    cursor = PatientAsOfCursor(config, run_id="R")
    assert cursor.advance(0, ()) == ()
    req = receipt(
        config,
        event="REQ",
        available=2.0,
        payload=Request(
            admission_mode="urgences", age_band="85_plus", isolation=False, oxygen=False
        ),
    )
    waiting = cursor.advance(2, [req])[0]
    assert waiting.status == "awaiting_admission" and waiting.current_unit_id is None
    admitted = cursor.advance(5, [receipt(config, event="ADM", hour=3.0, available=5.0)])[0]
    assert admitted.status == "admitted" and admitted.elapsed_stay_h == 2
    assert not admitted.admission_missing and not admitted.request_missing


def test_transfer_without_admission_keeps_missing_duration(config: HospitalConfig) -> None:
    a, b = (u.unit_id for u in config.units[:2])
    row = PatientAsOfCursor(config, run_id="R").advance(
        4,
        [
            receipt(
                config, unit=b, hour=3.0, payload=Transfer(from_unit_id=a, from_bed_id=3, bed_id=1)
            )
        ],
    )[0]
    assert row.current_unit_id == b and row.admission_missing and row.elapsed_stay_h is None
    assert row.internal_movements == 1


def test_corrections_rebuild_history_without_counting_another_move(config: HospitalConfig) -> None:
    a, b = (u.unit_id for u in config.units[:2])
    move = receipt(
        config,
        event="MOVE",
        hour=2.0,
        unit=b,
        payload=Transfer(from_unit_id=a, from_bed_id=3, bed_id=8),
    )
    corrected = receipt(
        config,
        event="MOVE",
        hour=2.0,
        unit=b,
        available=5.0,
        version=2,
        payload=Transfer(from_unit_id=a, from_bed_id=3, bed_id=7),
    )
    cursor = PatientAsOfCursor(config, run_id="R")
    before = cursor.advance(3, [receipt(config), move])[0]
    after = cursor.advance(5, [corrected])[0]
    assert before.bed_id == 8 and after.bed_id == 7
    assert before.internal_movements == after.internal_movements == 1
    # Late v1 and a transport retry cannot undo v2 or refresh event age.
    retry = corrected.model_copy(
        update={"delivery_id": "retry", "ingested_h": 6.0, "available_h": 6.0}
    )
    after_retry = cursor.advance(6, [move, retry])[0]
    assert after_retry.bed_id == 7 and after_retry.last_information_age_h == 4.0
    assert after_retry.sources == after.sources


def test_old_admission_revision_does_not_undo_later_transfer(config: HospitalConfig) -> None:
    a, b = (u.unit_id for u in config.units[:2])
    cursor = PatientAsOfCursor(config, run_id="R")
    cursor.advance(
        4,
        [
            receipt(config),
            receipt(
                config,
                event="MOVE",
                hour=3.0,
                unit=b,
                payload=Transfer(from_unit_id=a, from_bed_id=3, bed_id=7),
            ),
        ],
    )
    row = cursor.advance(
        6, [receipt(config, available=6.0, version=2, payload=Admission(home_unit_id=a, bed_id=2))]
    )[0]
    assert row.current_unit_id == b and row.bed_id == 7 and row.internal_movements == 1


def test_late_departure_and_void_revision_do_not_rewrite_past(config: HospitalConfig) -> None:
    cursor = PatientAsOfCursor(config, run_id="R")
    past = cursor.advance(2, [receipt(config)])[0]
    departure = receipt(
        config, event="OUT", hour=2.0, available=5.0, payload=Departure(destination="domicile")
    )
    assert cursor.advance(4, ())[0].status == "admitted"
    assert cursor.advance(5, [departure]) == ()
    void = receipt(
        config,
        event="OUT",
        hour=2.0,
        available=7.0,
        version=2,
        voided=True,
        payload=Departure(destination="domicile"),
    )
    restored = cursor.advance(7, [void])[0]
    assert restored.admission_h == past.admission_h == 1.0
    assert past.decision_h == 2 and past.sources[0].version == 1
    assert restored.last_event_h == 1.0  # cancellation receipt does not refresh clinical age


def test_same_hour_uses_source_order_not_receipt_order(config: HospitalConfig) -> None:
    a, b = (u.unit_id for u in config.units[:2])
    admitted = receipt(config, event="Z", order=1)
    moved = receipt(
        config,
        event="A",
        order=2,
        unit=b,
        payload=Transfer(from_unit_id=a, from_bed_id=3, bed_id=7),
    )
    row = PatientAsOfCursor(config, run_id="R").advance(2, [moved, admitted])[0]
    assert row.current_unit_id == b


def test_lost_departure_and_bed_reuse_are_uncertainty_not_invented_exit(
    config: HospitalConfig,
) -> None:
    cursor = PatientAsOfCursor(config, run_id="R", stale_after_h=24.0)
    first = receipt(config)
    cursor.advance(2, [first])
    second = receipt(config, event="OTHER", hour=30.0, stay="S2")
    rows = cursor.advance(40, [second])
    assert len(rows) == 2 and all(r.bed_conflict for r in rows)
    assert next(r for r in rows if r.stay_id == "S1").stale
    assert len(cursor.advance(150, ())) == 2  # no truth lookup or expiry masquerading as discharge


@pytest.mark.parametrize(
    "mutation", ["future", "identity", "version", "receipt", "topology", "payload"]
)
def test_bad_batch_rejected_atomically(config: HospitalConfig, mutation: str) -> None:
    cursor = PatientAsOfCursor(config, run_id="R")
    old = receipt(config)
    original = cursor.advance(2, [old])
    raw = receipt(config, version=2, available=3.0).model_dump()
    if mutation == "future":
        raw["available_h"] = 99.0
    elif mutation == "identity":
        raw["stay_id"] = "OTHER"
    elif mutation == "version":
        raw.update(event_version=1, replaces_version=None, delivery_id="conflict")
        raw["payload"]["bed_id"] = 99
    elif mutation == "receipt":
        raw["delivery_id"] = old.delivery_id
    elif mutation == "topology":
        raw["pole_id"] = "UNKNOWN"
    else:
        raw["payload"]["future_ready_h"] = 99
    with pytest.raises(ValueError):
        cursor.advance(
            3, [receipt(config, event="NEW", stay="NEW"), PatientDelivery.model_validate(raw)]
        )
    assert cursor.hour == 2 and cursor.advance(2, ()) == original


@pytest.mark.parametrize("mutation", ["future_source", "duration", "stale", "extra"])
def test_feature_mutations_detected(config: HospitalConfig, mutation: str) -> None:
    raw = PatientAsOfCursor(config, run_id="R").advance(2, [receipt(config)])[0].model_dump()
    if mutation == "future_source":
        raw["sources"][0]["available_h"] = 10.0
    elif mutation == "duration":
        raw["elapsed_stay_h"] = 999.0
    elif mutation == "stale":
        raw["stale"] = True
    else:
        raw["departure_h"] = 3.0
    with pytest.raises(ValueError):
        PatientRow.model_validate(raw)


def test_future_deliveries_leave_prefix_unchanged(config: HospitalConfig) -> None:
    base = [receipt(config)]
    later = receipt(config, version=2, available=50.0)
    left = [r for r in replay_patients(base, config, run_id="R") if r.decision_h < 50]
    right = [r for r in replay_patients([later, *base], config, run_id="R") if r.decision_h < 50]
    assert left == right


def test_truth_and_targets_use_event_boundaries_and_right_censoring(config: HospitalConfig) -> None:
    truth = build_patient_truth(truth_events(config, exit_hour=25), config)
    stay = next(iter(truth.values()))
    row = PatientAsOfCursor(config, run_id="R").advance(
        2, [receipt(config, hour=2.0, stay=stay.stay_id)]
    )[0]
    target = patient_target(row, truth)
    assert stay.admission_h == 2.0 and stay.departure_h == 26.0
    assert target["departure_24h"] is True and target["remaining_stay_h"] == 24.0
    at_exit = PatientRow.model_validate(
        {
            **row.model_dump(),
            "decision_h": 26,
            "elapsed_stay_h": 24.0,
            "last_information_age_h": 24.0,
        }
    )
    target = patient_target(at_exit, truth)
    assert not target["at_risk"] and target["departure_24h"] is None
    censored = build_patient_truth(truth_events(config, exit_hour=None), config)
    end = config.days * 24 - 1
    last = PatientAsOfCursor(config, run_id="R").advance(
        end, [receipt(config, hour=2.0, stay=stay.stay_id)]
    )[0]
    target = patient_target(last, censored)
    assert target["departure_24h"] is None and target["departure_24h_censored"]
    assert target["remaining_stay_h"] is None and target["observed_followup_h"] == 1.0
    assert next(iter(censored.values())).departure_h is None
    early = patient_target(row, censored)
    assert early["departure_24h"] is False and not early["departure_24h_censored"]


def test_known_positive_near_extraction_is_not_censored(config: HospitalConfig) -> None:
    events = truth_events(config, exit_hour=config.days * 24 - 1)
    truth = build_patient_truth(events, config)
    stay = next(iter(truth))
    row = PatientAsOfCursor(config, run_id="R").advance(
        config.days * 24 - 2, [receipt(config, stay=stay)]
    )[0]
    target = patient_target(row, truth)
    assert target["departure_72h"] is True and not target["departure_72h_censored"]


@pytest.mark.parametrize("mutation", ["future", "open_exit", "missing_admission"])
def test_censored_truth_mutations_rejected(config: HospitalConfig, mutation: str) -> None:
    value = next(
        iter(build_patient_truth(truth_events(config, None), config).values())
    ).model_dump()
    if mutation == "future":
        value["admission_h"] = config.days * 24 + 1
    elif mutation == "open_exit":
        value["departure_h"] = 20.0
    else:
        value.update(
            termination="departed",
            right_censored=False,
            admission_h=None,
            departure_h=20.0,
            closed_h=20.0,
        )
    with pytest.raises(ValueError):
        TruthStay.model_validate(value)


@pytest.fixture(scope="module")
def dataset(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, HospitalConfig]:
    raw = json.loads(
        Path("configs/synthetic/hospital_observation_intermittent_v1.json").read_text()
    )
    raw.update(days=7, warmup_days=2)
    raw["observation"]["outages"] = [
        {
            "outage_id": "TEST_OUTAGE",
            "starts_at": "2025-01-02T06:00:00+01:00",
            "ends_at": "2025-01-03T18:00:00+01:00",
        }
    ]
    raw["observation"].update(revision_probability=0.5, duplicate_probability=0.5)
    config = HospitalConfig.model_validate(raw)
    root = tmp_path_factory.mktemp("patient-run")
    generate(config, root / "truth")
    return root, config


def test_online_offline_and_outages_match(dataset: tuple[Path, HospitalConfig]) -> None:
    root, config = dataset
    events = list(_events(root / "truth"))
    offline = observe_patients(events, config)
    assert offline == observe_patients(reversed(events), config)
    assert all(not 30 <= r.available_h < 66 and not 30 <= r.ingested_h < 66 for r in offline)
    assert any(30 <= r.event_h < 66 and r.available_h >= 66 for r in offline)
    assert any(r.event_version == 2 for r in offline)
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        grouped[e["h"]].append(e)
    online = OnlinePatients(config)
    cursor = PatientAsOfCursor(config, run_id="R")
    received: list[PatientDelivery] = []
    current: list[PatientRow] = []
    for hour in range(-config.warmup_days * 24, config.days * 24):
        online.push(hour, grouped[hour])
        if hour < 0:
            continue
        batch = online.receive(hour)
        received.extend(batch)
        current.extend(cursor.advance(hour, batch))
    received.extend(online.receive(config.days * 24))
    assert received == offline
    assert current == list(replay_patients(offline, config, run_id="R"))
    assert online.pending
    with pytest.raises(ValueError):
        online.receive(config.days * 24 + 1)
    with pytest.raises(ValueError):
        online.push(config.days * 24, [])


def test_pipeline_reproducibility_immutable_source_and_label_isolation(
    dataset: tuple[Path, HospitalConfig],
) -> None:
    root, config = dataset
    source_hash = hashlib.sha256((root / "truth/manifest.json").read_bytes()).hexdigest()
    a = prepare_patient_run(root / "truth", root / "a")
    b = prepare_patient_run(root / "truth", root / "b")
    assert a == b and a["counts"]["features"] == a["counts"]["targets"] > 0
    for name, digest in a["files_sha256"].items():
        assert hashlib.sha256((root / "a" / name).read_bytes()).hexdigest() == digest
        assert (root / "a" / name).read_bytes() == (root / "b" / name).read_bytes()
    assert hashlib.sha256((root / "truth/manifest.json").read_bytes()).hexdigest() == source_hash
    with gzip.open(root / "a/features/patients_asof.jsonl.gz", "rt") as stream:
        rows = [PatientRow.model_validate_json(line) for line in stream]
    assert rows and all(r.decision_h < config.days * 24 for r in rows)
    assert all(s.available_h <= r.decision_h for r in rows for s in r.sources)
    assert all("departure_h" not in r.model_dump() for r in rows)
    with pytest.raises(FileExistsError):
        prepare_patient_run(root / "truth", root / "a")
    with pytest.raises(ValueError):
        prepare_patient_run(root / "truth", root / "truth/nested")


def test_all_missing_produces_no_fabricated_patients(
    config: HospitalConfig, tmp_path: Path
) -> None:
    config = HospitalConfig.model_validate(
        {**config.model_dump(), "observation": {"mode": "site_v1", "missing_probability": 1.0}}
    )
    generate(config, tmp_path / "truth")
    report = prepare_patient_run(tmp_path / "truth", tmp_path / "patients")
    assert (
        report["counts"]["deliveries"]
        == report["counts"]["features"]
        == report["counts"]["targets"]
        == 0
    )
    assert report["counts"]["truth_stays"] > 0


def test_cohort_patient_output_preserves_partition_and_test_reservation(tmp_path: Path) -> None:
    raw = json.loads(Path("configs/synthetic/cohort_structures_v1.json").read_text())
    raw.update(days=2, warmup_days=1)
    for spec in raw["structures"]:
        spec.update(hospitals=1, replicates=1)
    cohort.freeze(CohortPlan.model_validate(raw), tmp_path / "registry")
    report = cohort.materialize(tmp_path / "registry", tmp_path / "cohort", with_patients=True)
    assert report["with_patients"] and not report["test_access"]["opened"]
    assert len(report["reserved_world_ids"]) == 1
    for w in report["worlds"]:
        manifest = json.loads(
            (tmp_path / "cohort" / w["patient_path"] / "manifest.json").read_text()
        )
        assert (
            manifest["partition"] == w["partition"] and manifest["hospital_id"] == w["hospital_id"]
        )
    with pytest.raises(ValueError, match="test_protocol"):
        cohort.materialize(
            tmp_path / "registry", tmp_path / "forbidden", partitions=("test",), with_patients=True
        )


@pytest.mark.parametrize(
    "reason", ["ORIENTATION_HORS_PERIMETRE", "DEPROGRAMMATION", "TRANSFERT_REFUSE"]
)
def test_nonadmission_closes_request_without_fabricating_admission(
    config: HospitalConfig, reason: str
) -> None:
    events = truth_events(config)[:1]
    end = {
        **events[0],
        "event_id": f"{config.hospital_id}:E000000002",
        "h": 5,
        "type": reason,
        "payload": {},
    }
    truth = build_patient_truth([*events, end], config)
    stay = next(iter(truth.values()))
    assert stay.termination == "not_admitted" and stay.admission_h is None
    assert stay.departure_h is None and not stay.right_censored
    first, last = source_movement(events[0], config), source_movement(end, config)
    assert first is not None and last is not None
    cursor = PatientAsOfCursor(config, run_id="R")
    assert cursor.advance(2, [first])[0].status == "awaiting_admission"
    assert cursor.advance(6, [last]) == ()


@pytest.mark.parametrize("family", ["v041", "local_v1", "hybrid_v1"])
def test_ideal_movement_census_matches_every_physical_unit_hour(
    config: HospitalConfig, tmp_path: Path, family: str
) -> None:
    config = HospitalConfig.model_validate(
        {
            **config.model_dump(),
            "days": 3,
            "mechanism_family": family,
            "observation": {
                "mode": "site_v1",
                "missing_probability": 0.0,
                "recording_delay_median_minutes": 0.0,
                "ingestion_delay_min_minutes": 0.0,
                "ingestion_delay_max_minutes": 0.0,
                "availability_delay_minutes": 0.0,
                "revision_probability": 0.0,
                "duplicate_probability": 0.0,
            },
        }
    )
    generate(config, tmp_path / "truth")
    events = list(_events(tmp_path / "truth"))
    expected = {
        (e["h"] + 1, e["unit_id"]): e["payload"]["lits_occupes"]
        for e in events
        if e["type"] == "ETAT_UNITE"
    }
    rows = list(replay_patients(observe_patients(events, config), config, run_id="R"))
    counts = Counter((r.decision_h, r.current_unit_id) for r in rows if r.status == "admitted")
    assert not any(r.bed_conflict for r in rows)
    for hour in range(config.days * 24):
        for unit in config.units:
            assert counts[hour, unit.unit_id] == expected[hour, unit.unit_id]


def test_future_outage_does_not_change_past_patient_receipts(config: HospitalConfig) -> None:
    raw = {
        **config.model_dump(),
        "observation": {
            "mode": "site_v1",
            "revision_probability": 1.0,
            "duplicate_probability": 1.0,
        },
    }
    base = HospitalConfig.model_validate(raw)
    raw["observation"]["outages"] = [
        {
            "outage_id": "FUTURE",
            "starts_at": "2025-01-03T00:00:00+01:00",
            "ends_at": "2025-01-04T00:00:00+01:00",
        }
    ]
    changed = HospitalConfig.model_validate(raw)
    events = truth_events(base)
    first = [r for r in observe_patients(events, base) if r.available_h < 48]
    second = [r for r in observe_patients(events, changed) if r.available_h < 48]
    assert first == second


def test_source_after_extraction_and_duplicate_admission_rejected(config: HospitalConfig) -> None:
    events = truth_events(config)
    events[-1]["h"] = config.days * 24
    with pytest.raises(ValueError, match="outside"):
        build_patient_truth(events, config)
    events = truth_events(config, None)
    events.append({**events[1], "event_id": f"{config.hospital_id}:E000000003"})
    with pytest.raises(ValueError, match="Duplicate admission"):
        build_patient_truth(events, config)
