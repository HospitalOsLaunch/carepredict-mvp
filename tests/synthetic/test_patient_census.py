"""Census scope, non-anticipation, revisions and unresolved presence contracts."""

from __future__ import annotations

import gzip
import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest
import test_patients as patient_helpers
from test_patients import receipt, truth_events

from hospitalos.synthetic import cohort
from hospitalos.synthetic.config import HospitalConfig
from hospitalos.synthetic.learning import _events
from hospitalos.synthetic.patient_asof import PatientAsOfCursor, PatientRow
from hospitalos.synthetic.patient_census import (
    CensusDelivery,
    CensusMember,
    CensusProfile,
    OnlineCensus,
    observe_censuses,
)
from hospitalos.synthetic.patient_learning import prepare_patient_run
from hospitalos.synthetic.patient_observations import Departure, Request, Transfer

config = patient_helpers.config
dataset = patient_helpers.dataset


def census(
    config: HospitalConfig,
    *,
    event: str = "C1",
    hour: float = 10.0,
    available: float | None = None,
    unit: str | None = None,
    members: tuple[CensusMember, ...] = (),
    complete: bool = True,
    version: int = 1,
    **extra: Any,
) -> CensusDelivery:
    unit = unit or config.units[0].unit_id
    clock = hour if available is None else available
    return CensusDelivery(
        delivery_id=f"{event}:v{version}",
        event_id=event,
        event_version=version,
        replaces_version=version - 1 if version > 1 else None,
        hospital_id=config.hospital_id,
        pole_id=config.unit_poles[unit],
        unit_id=unit,
        event_h=hour,
        recorded_h=hour,
        ingested_h=clock,
        available_h=clock,
        complete=complete,
        members=members,
        **extra,
    )


def test_absence_is_local_not_discharge_and_waits_for_availability(config: HospitalConfig) -> None:
    cursor = PatientAsOfCursor(config, run_id="R")
    before = cursor.advance(10, [receipt(config)])[0]
    assert cursor.advance(11, [])
    assert not cursor.advance(12, [], [census(config, available=12.0)])
    change = cursor.reconciliations[0]
    assert change.status == "unit_absence" and change.closure_kind is None
    assert change.absence_h == 10 and change.absence_unit_id == config.units[0].unit_id
    assert change.decision_h == 12 and change.trigger_delivery_ids == ("C1:v1",)
    assert before.status == "admitted"  # Previously emitted row is immutable.
    assert cursor.states["S1"]["admission_h"] == 1


@pytest.mark.parametrize("complete", [False, True])
def test_partial_empty_and_other_unit_never_remove_occupancy(
    config: HospitalConfig, complete: bool
) -> None:
    cursor = PatientAsOfCursor(config, run_id="R")
    rows = cursor.advance(
        10,
        [receipt(config)],
        [
            census(
                config,
                complete=complete,
                unit=config.units[1].unit_id if complete else config.units[0].unit_id,
            )
        ],
    )
    assert len(rows) == 1 and rows[0].last_event_h == 1


def test_census_cannot_close_an_unadmitted_request(config: HospitalConfig) -> None:
    request = Request(admission_mode="urgences", age_band="under_65", isolation=False, oxygen=False)
    rows = PatientAsOfCursor(config, run_id="R").advance(
        10,
        [receipt(config, payload=request)],
        [census(config)],
    )
    assert rows[0].status == "awaiting_admission" and rows[0].admission_missing


def test_positive_partial_recovers_stay_without_inventing_admission(config: HospitalConfig) -> None:
    row = PatientAsOfCursor(config, run_id="R").advance(
        10,
        [],
        [
            census(
                config,
                complete=False,
                members=(CensusMember(stay_id="S1", bed_id=5),),
            )
        ],
    )[0]
    assert row.status == "admitted" and row.presence_basis == "census" and row.bed_id == 5
    assert row.admission_missing and row.request_missing and row.elapsed_stay_h is None
    assert row.age_band is None and row.home_unit_id is None and row.internal_movements == 0
    assert row.sources[0].source == "RECENSEMENT_UNITE" and row.sources[0].complete is False


@pytest.mark.parametrize("correction", ["partial", "voided", "member"])
def test_revision_retracts_absence_only_when_received(
    config: HospitalConfig, correction: str
) -> None:
    cursor = PatientAsOfCursor(config, run_id="R")
    assert not cursor.advance(10, [receipt(config)], [census(config)])
    assert not cursor.advance(11, [])
    extra: dict[str, Any] = (
        {"complete": False}
        if correction == "partial"
        else (
            {"voided": True}
            if correction == "voided"
            else {"members": (CensusMember(stay_id="S1", bed_id=3),)}
        )
    )
    row = cursor.advance(12, [], [census(config, version=2, available=12.0, **extra)])[0]
    assert row.status == "admitted" and row.bed_id == 3
    assert cursor.reconciliations[0].absence_h is None


def test_census_only_void_is_audited_as_unobserved(config: HospitalConfig) -> None:
    cursor = PatientAsOfCursor(config, run_id="R")
    members = (CensusMember(stay_id="S1", bed_id=3),)
    assert cursor.advance(10, [], [census(config, members=members)])
    assert not cursor.advance(
        12, [], [census(config, members=members, version=2, available=12.0, voided=True)]
    )
    assert cursor.reconciliations[0].status == "unobserved"
    assert cursor.reconciliations[0].sources[0].voided


def test_late_census_never_undoes_later_transfer_or_departure(config: HospitalConfig) -> None:
    a, b = config.units[0].unit_id, config.units[1].unit_id
    cursor = PatientAsOfCursor(config, run_id="R")
    transfer = receipt(
        config,
        event="E2",
        hour=15.0,
        unit=b,
        payload=Transfer(from_unit_id=a, from_bed_id=3, bed_id=8),
    )
    assert cursor.advance(15, [receipt(config), transfer])[0].current_unit_id == b
    row = cursor.advance(20, [], [census(config, available=20.0)])[0]
    assert row.current_unit_id == b and row.internal_movements == 1
    assert not cursor.advance(
        21, [receipt(config, event="E3", hour=21.0, payload=Departure(destination="domicile"))]
    )
    assert not cursor.advance(
        22,
        [],
        [
            census(
                config,
                event="C2",
                hour=18.0,
                available=22.0,
                unit=b,
                members=(CensusMember(stay_id="S1", bed_id=8),),
            )
        ],
    )


def test_census_at_destination_recovers_missing_transfer_without_inventing_it(
    config: HospitalConfig,
) -> None:
    cursor = PatientAsOfCursor(config, run_id="R")
    assert not cursor.advance(10, [receipt(config)], [census(config)])
    b = config.units[-1].unit_id
    row = cursor.advance(
        11,
        [],
        [
            census(
                config,
                event="C2",
                unit=b,
                hour=11.0,
                members=(CensusMember(stay_id="S1", bed_id=8),),
            )
        ],
    )[0]
    assert row.current_unit_id == b and row.current_pole_id == config.unit_poles[b]
    assert row.internal_movements == 0 and row.admission_h == 1


def test_late_admission_is_compared_to_already_known_census(config: HospitalConfig) -> None:
    cursor = PatientAsOfCursor(config, run_id="R")
    assert not cursor.advance(10, [], [census(config)])
    assert not cursor.advance(12, [receipt(config, available=12.0)])
    assert cursor.reconciliations[0].status == "unit_absence"


def test_retries_and_reversed_versions_do_not_refresh_census(config: HospitalConfig) -> None:
    cursor = PatientAsOfCursor(config, run_id="R")
    v2 = census(
        config,
        version=2,
        complete=False,
        available=11.0,
        members=(CensusMember(stay_id="S1", bed_id=4),),
    )
    row = cursor.advance(11, [receipt(config)], [v2])[0]
    duplicate = v2.model_copy(
        update={"delivery_id": "retry", "ingested_h": 12.0, "available_h": 12.0}
    )
    later = cursor.advance(12, [], [duplicate, census(config, available=12.0)])[0]
    assert later.sources == row.sources and later.last_event_h == 10 and later.bed_id == 4
    assert cursor.reconciliations == ()


def test_equal_boundary_census_follows_movement(config: HospitalConfig) -> None:
    cursor = PatientAsOfCursor(config, run_id="R")
    assert not cursor.advance(10, [receipt(config, hour=10.0)], [census(config)])
    assert cursor.reconciliations[0].status == "unit_absence"


def test_census_contradicting_recorded_departure_flags_conflict(config: HospitalConfig) -> None:
    cursor = PatientAsOfCursor(config, run_id="R")
    assert not cursor.advance(
        5,
        [
            receipt(config),
            receipt(config, event="E2", hour=5.0, payload=Departure(destination="domicile")),
        ],
    )
    row = cursor.advance(10, [], [census(config, members=(CensusMember(stay_id="S1", bed_id=3),))])[
        0
    ]
    assert row.observation_conflict


def test_two_simultaneous_positive_locations_are_flagged(config: HospitalConfig) -> None:
    rows = [
        census(
            config, event=f"C{i}", unit=u.unit_id, members=(CensusMember(stay_id="S1", bed_id=3),)
        )
        for i, u in enumerate(config.units[:2])
    ]
    assert PatientAsOfCursor(config, run_id="R").advance(10, [], rows)[0].observation_conflict


@pytest.mark.parametrize("mutation", ["future", "topology", "identity", "version", "receipt"])
def test_bad_batch_is_atomic_including_constructed_census(
    config: HospitalConfig, mutation: str
) -> None:
    cursor = PatientAsOfCursor(config, run_id="R")
    first = census(config, complete=False)
    original = cursor.advance(10, [receipt(config)], [first])
    bad = first.model_copy(update={"delivery_id": "bad"})
    if mutation == "future":
        bad = bad.model_copy(update={"available_h": 20.0})
    elif mutation == "topology":
        bad = bad.model_copy(update={"pole_id": "WRONG"})
    elif mutation == "identity":
        bad = bad.model_copy(update={"event_h": 9.0, "event_version": 2, "replaces_version": 1})
    elif mutation == "version":
        bad = bad.model_copy(update={"complete": True})
    else:
        bad = bad.model_copy(update={"delivery_id": first.delivery_id, "available_h": 11.0})
    with pytest.raises(ValueError):
        cursor.advance(11, [receipt(config, event="E3", stay="S2")], [bad])
    assert cursor.hour == 10 and "S2" not in cursor.history
    assert cursor.advance(10, []) == original


@pytest.mark.parametrize(
    "mutation", ["future_field", "duplicate_stay", "duplicate_bed", "clock", "revision", "boolean"]
)
def test_closed_census_schema_rejects_mutations(config: HospitalConfig, mutation: str) -> None:
    raw = census(config).model_dump()
    if mutation == "future_field":
        raw["medical_discharge_h"] = 100
    elif mutation in ("duplicate_stay", "duplicate_bed"):
        raw["members"] = [
            {"stay_id": "S1", "bed_id": 1},
            {
                "stay_id": "S1" if mutation == "duplicate_stay" else "S2",
                "bed_id": 2 if mutation == "duplicate_stay" else 1,
            },
        ]
    elif mutation == "clock":
        raw["available_h"] = 1.0
    elif mutation == "revision":
        raw["replaces_version"] = 1
    else:
        raw["complete"] = "true"
    with pytest.raises(ValueError):
        CensusDelivery.model_validate(raw)


def test_online_offline_censuses_outages_and_future_mutation(
    dataset: tuple[Path, HospitalConfig],
) -> None:
    root, config = dataset
    events = list(_events(root / "truth"))
    rows = observe_censuses(events, config)
    assert rows == observe_censuses(reversed(events), config)
    assert any(r.event_version == 2 for r in rows)
    assert any(not r.complete for r in rows)
    assert len(rows) > len({(r.event_id, r.event_version) for r in rows})
    assert all(not 30 <= r.available_h < 66 and not 30 <= r.ingested_h < 66 for r in rows)
    assert any(30 <= r.event_h < 66 and r.available_h >= 66 for r in rows)
    batches: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        batches[event["h"]].append(event)
    online = OnlineCensus(config)
    received: list[CensusDelivery] = []
    for hour in range(-config.warmup_days * 24, config.days * 24):
        online.push(hour, batches[hour])
        received.extend(online.receive(hour + 1))
    assert rows == received
    mutated = [e for e in events if e["h"] < 72]
    assert [r for r in rows if r.available_h <= 72] == [
        r for r in observe_censuses(mutated, config) if r.available_h <= 72
    ]
    with pytest.raises(ValueError):
        online.receive(config.days * 24 + 1)


def test_census_uses_current_occupancy_and_empty_is_observed(config: HospitalConfig) -> None:
    raw = config.model_dump()
    raw["observation"] = {
        "mode": "site_v1",
        "missing_probability": 0.0,
        "recording_delay_median_minutes": 0.0,
        "ingestion_delay_min_minutes": 0.0,
        "ingestion_delay_max_minutes": 0.0,
        "availability_delay_minutes": 0.0,
        "revision_probability": 0.0,
        "duplicate_probability": 0.0,
    }
    cfg = HospitalConfig.model_validate(raw)
    rows = observe_censuses(truth_events(cfg, 25), cfg, CensusProfile(partial_probability=0.0))
    unit = cfg.units[0].unit_id
    assert len(next(r for r in rows if r.unit_id == unit and r.event_h == 24).members) == 1
    assert not next(r for r in rows if r.unit_id == unit and r.event_h == 48).members
    assert any(r.event_h == cfg.days * 24 for r in rows)  # Exported, never used before extraction.
    raw["observation"]["missing_probability"] = 1.0
    assert not observe_censuses(truth_events(cfg), HospitalConfig.model_validate(raw))


def test_reconciled_pipeline_is_reproducible_separated_and_hashed(
    dataset: tuple[Path, HospitalConfig],
) -> None:
    root, _ = dataset
    before = hashlib.sha256((root / "truth/manifest.json").read_bytes()).hexdigest()
    profile = CensusProfile(interval_h=12)
    a = prepare_patient_run(root / "truth", root / "census_a", census_profile=profile)
    b = prepare_patient_run(root / "truth", root / "census_b", census_profile=profile)
    assert a == b and a["counts"]["census_presence_rows"] > 0
    assert a["counts"]["features"] == a["counts"]["targets"]
    assert before == hashlib.sha256((root / "truth/manifest.json").read_bytes()).hexdigest()
    for name, digest in a["files_sha256"].items():
        assert hashlib.sha256((root / "census_a" / name).read_bytes()).hexdigest() == digest
    with gzip.open(root / "census_a/features/patients_asof.jsonl.gz", "rt") as stream:
        for line in stream:
            row = PatientRow.model_validate_json(line)
            assert all(s.available_h <= row.decision_h for s in row.sources)
            assert "departure_h" not in line and "at_risk" not in line
    with pytest.raises(FileExistsError):
        prepare_patient_run(root / "truth", root / "census_a", census_profile=profile)


def test_cohort_census_requires_patient_pipeline(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="requires with_patients"):
        cohort.materialize(tmp_path / "missing", tmp_path / "out", with_census=True)


def test_retracting_old_absence_preserves_newer_complete_absence(config: HospitalConfig) -> None:
    cursor = PatientAsOfCursor(config, run_id="R")
    cursor.advance(10, [receipt(config)], [census(config)])
    cursor.advance(20, [], [census(config, event="C2", hour=20.0)])
    assert not cursor.advance(21, [], [census(config, version=2, available=21.0, complete=False)])
    change = cursor.reconciliations[0]
    assert change.status == "unit_absence" and change.absence_h == 20


def test_silence_and_partial_census_cannot_expire_patient(config: HospitalConfig) -> None:
    cursor = PatientAsOfCursor(config, run_id="R")
    cursor.advance(10, [receipt(config)])
    row = cursor.advance(160, [], [census(config, hour=150.0, complete=False)])[0]
    assert row.status == "admitted" and row.stale and row.last_event_h == 1
