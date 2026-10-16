"""Available care evidence, workflow scope, missingness and target isolation."""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

import pytest
import test_patients as patient_helpers
from test_patients import receipt

from hospitalos.synthetic import cohort
from hospitalos.synthetic.config import HospitalConfig
from hospitalos.synthetic.learning import _events
from hospitalos.synthetic.patient_asof import PatientAsOfCursor, PatientRow
from hospitalos.synthetic.patient_care import (
    SOURCES,
    CareAssessment,
    CareDelivery,
    DeparturePlan,
    Downstream,
    HomeHelp,
    OnlineCare,
    RequestedDestination,
    observe_care,
    source_care,
)
from hospitalos.synthetic.patient_care_asof import CareAsOfCursor, PatientCareRow, replay_care
from hospitalos.synthetic.patient_census import CensusProfile
from hospitalos.synthetic.patient_learning import prepare_patient_run

config = patient_helpers.config
dataset = patient_helpers.dataset


def care(
    config: HospitalConfig,
    *,
    event: str = "C1",
    hour: float = 2.0,
    available: float | None = None,
    payload: Any = None,
    version: int = 1,
    unit: str | None = None,
    order: int = 1,
    **extra: Any,
) -> CareDelivery:
    unit = unit or config.units[0].unit_id
    payload = payload or CareAssessment(minutes_per_24h=200.0, dependence=2, mobility="aide")
    clock = hour if available is None else available
    return CareDelivery(
        delivery_id=f"{event}:v{version}",
        event_id=event,
        stay_id="S1",
        hospital_id=config.hospital_id,
        pole_id=config.unit_poles[unit],
        unit_id=unit,
        event_order=order,
        event_version=version,
        replaces_version=version - 1 if version > 1 else None,
        source=SOURCES[payload.kind],
        event_h=hour,
        recorded_h=hour,
        ingested_h=clock,
        available_h=clock,
        payload=payload,
        **extra,
    )


def patient(config: HospitalConfig, hour: int = 10) -> PatientRow:
    return PatientAsOfCursor(config, run_id="R").advance(hour, [receipt(config)])[0]


def source(
    config: HospitalConfig, kind: str, payload: dict[str, Any], hour: int = 1, index: int = 1
) -> dict[str, Any]:
    unit = config.units[0].unit_id
    return {
        "event_id": f"{config.hospital_id}:E{index:09d}",
        "stay_id": f"{config.hospital_id}:S000001",
        "h": hour,
        "hospital_id": config.hospital_id,
        "pole_id": config.unit_poles[unit],
        "unit_id": unit,
        "type": kind,
        "payload": payload,
    }


@pytest.mark.parametrize(
    "kind,payload,expected",
    [
        (
            "EVALUATION_CHARGE",
            {
                "minutes_soins_24h": 200.0,
                "dependance": 2,
                "mobilite": "aide",
                "proxy_non_siips": True,
            },
            "assessment",
        ),
        (
            "DATE_SORTIE_PREVISIONNELLE",
            {"date_prevue": "2025-01-10", "revision": 99},
            "departure_plan",
        ),
        ("DESTINATION_DEMANDEE", {"destination_demandee": "SMR", "revision": 99}, "destination"),
        ("DEMANDE_AVAL", {"type_aval": "SMR"}, "downstream"),
        ("DEMANDE_AVAL_ANNULEE", {}, "downstream"),
        ("PLACE_AVAL_CONFIRMEE", {"type_aval": "EHPAD"}, "downstream"),
        ("AIDE_DOMICILE_DEMANDE", {}, "home_help"),
        ("AIDE_DOMICILE_ORGANISEE", {}, "home_help"),
    ],
)
def test_source_projection_is_closed_and_ignores_future_fields(
    config: HospitalConfig,
    kind: str,
    payload: dict[str, Any],
    expected: str,
) -> None:
    event = source(config, kind, payload)
    row = source_care(event, config)
    assert row is not None and row.payload.kind == expected and row.event_h == 2
    altered = {
        **event,
        "payload": {**payload, "ready_h": 1000, "departure_h": 2000, "destination_finale": "deces"},
    }
    assert source_care(altered, config) == row
    assert "revision" not in row.payload.model_dump() and "ready_h" not in row.model_dump_json()


def test_absence_is_unknown_not_zero_and_evidence_does_not_create_patient(
    config: HospitalConfig,
) -> None:
    cursor = CareAsOfCursor(config)
    cursor.advance(10, [])
    row = cursor.for_patient(patient(config))
    assert row.assessment_missing and row.departure_plan_missing
    assert row.downstream is None and row.downstream_request_missing is None
    assert row.planned_days_remaining is row.plan_overdue is None
    assert list(replay_care([], [care(config)], config)) == []


def test_each_fact_has_own_freshness_and_reporting_unit(config: HospitalConfig) -> None:
    cursor = CareAsOfCursor(config)
    assessment = care(config, unit=config.units[-1].unit_id)
    plan = care(config, event="P1", hour=120.0, payload=DeparturePlan(planned_day=6))
    cursor.advance(121, [assessment, plan])
    row = cursor.for_patient(patient(config, 121))
    assert row.assessment and row.assessment.stale and row.assessment.age_h == 119
    assert row.assessment.reporting_unit_id == config.units[-1].unit_id
    assert row.departure_plan and not row.departure_plan.stale
    assert row.planned_days_remaining == 1
    assert patient(config, 121).current_unit_id == config.units[0].unit_id


def test_revisions_replace_values_without_counting_new_staff_updates(
    config: HospitalConfig,
) -> None:
    cursor = CareAsOfCursor(config)
    first = care(config, payload=DeparturePlan(planned_day=3))
    cursor.advance(3, [first])
    before = cursor.for_patient(patient(config, 3))
    second = care(config, available=5.0, payload=DeparturePlan(planned_day=4), version=2)
    cursor.advance(5, [second])
    after = cursor.for_patient(patient(config, 5))
    assert before.planned_days_remaining == 3 and after.planned_days_remaining == 4
    assert after.plan_updates_known == 0 and after.corrected_events_known == 1
    later = care(config, event="C2", hour=6.0, payload=DeparturePlan(planned_day=2))
    cursor.advance(6, [later])
    assert cursor.for_patient(patient(config, 6)).plan_updates_known == 1


def test_old_correction_and_duplicate_do_not_override_new_plan(config: HospitalConfig) -> None:
    cursor = CareAsOfCursor(config)
    old = care(config, payload=DeparturePlan(planned_day=3))
    new = care(config, event="P2", hour=4.0, payload=DeparturePlan(planned_day=5))
    cursor.advance(4, [old, new])
    before = cursor.for_patient(patient(config, 4))
    correction = care(config, available=8.0, version=2, payload=DeparturePlan(planned_day=10))
    retry = new.model_copy(update={"delivery_id": "retry", "ingested_h": 8.0, "available_h": 8.0})
    cursor.advance(8, [correction, retry])
    row = cursor.for_patient(patient(config, 8))
    assert row.departure_plan and before.departure_plan
    assert row.departure_plan.event_id == "P2" and row.departure_plan.available_h == 4
    assert row.planned_days_remaining == 5 and row.plan_updates_known == 1


def test_voided_plan_reverts_to_older_known_forecast(config: HospitalConfig) -> None:
    cursor = CareAsOfCursor(config)
    cursor.advance(
        4,
        [
            care(config, payload=DeparturePlan(planned_day=2)),
            care(config, event="P2", hour=4.0, payload=DeparturePlan(planned_day=3)),
        ],
    )
    cursor.advance(
        8,
        [
            care(
                config,
                event="P2",
                hour=4.0,
                available=8.0,
                payload=DeparturePlan(planned_day=3),
                version=2,
                voided=True,
            )
        ],
    )
    row = cursor.for_patient(patient(config, 8))
    assert (
        row.planned_days_remaining == 2
        and row.voided_events_known == 1
        and row.plan_updates_known == 0
    )


def test_forecast_can_be_overdue_or_after_extraction(config: HospitalConfig) -> None:
    cursor = CareAsOfCursor(config)
    cursor.advance(100, [care(config, payload=DeparturePlan(planned_day=1))])
    row = cursor.for_patient(patient(config, 100))
    assert row.planned_days_remaining == -3 and row.plan_overdue is True
    cursor.advance(
        120, [care(config, event="P2", hour=120.0, payload=DeparturePlan(planned_day=400))]
    )
    row = cursor.for_patient(patient(config, 120))
    assert row.planned_days_remaining == 395 and row.plan_overdue is False


def request(
    config: HospitalConfig,
    event: str = "D1",
    hour: float = 2.0,
    destination: Literal["SMR", "EHPAD"] = "SMR",
) -> CareDelivery:
    return care(
        config,
        event=event,
        hour=hour,
        payload=Downstream(status="requested", request_id=event, destination=destination),
    )


@pytest.mark.parametrize("status", ["cancelled", "confirmed"])
def test_terminal_aval_status_has_no_wait_and_reopening_resets_clock(
    config: HospitalConfig, status: Any
) -> None:
    cursor = CareAsOfCursor(config)
    cursor.advance(10, [request(config)])
    row = cursor.for_patient(patient(config))
    assert row.downstream_wait_h == 8 and row.downstream_request_missing is False
    terminal = care(
        config,
        event="T1",
        hour=12.0,
        payload=Downstream(status=status, request_id="D1", destination="SMR"),
    )
    cursor.advance(12, [terminal])
    row = cursor.for_patient(patient(config, 12))
    assert (
        row.downstream_wait_h is None
        and row.downstream
        and isinstance(row.downstream.payload, Downstream)
        and row.downstream.payload.status == status
    )
    cursor.advance(20, [request(config, "D2", 15.0, "EHPAD")])
    row = cursor.for_patient(patient(config, 20))
    assert (
        row.downstream_wait_h == 5
        and row.downstream
        and isinstance(row.downstream.payload, Downstream)
        and row.downstream.payload.request_id == "D2"
    )


def test_old_request_confirmation_never_closes_new_request(config: HospitalConfig) -> None:
    cursor = CareAsOfCursor(config)
    terminal = care(
        config,
        event="T1",
        hour=18.0,
        payload=Downstream(status="confirmed", request_id="D1", destination="SMR"),
    )
    cursor.advance(20, [request(config), request(config, "D2", 10.0, "EHPAD"), terminal])
    row = cursor.for_patient(patient(config, 20))
    assert row.downstream_wait_h == 10 and row.unmatched_downstream_events == 1


def test_missing_request_does_not_get_fabricated_from_confirmation(config: HospitalConfig) -> None:
    cursor = CareAsOfCursor(config)
    terminal = care(
        config,
        event="T1",
        hour=5.0,
        payload=Downstream(status="confirmed", request_id="D1", destination="SMR"),
    )
    cursor.advance(10, [terminal])
    row = cursor.for_patient(patient(config))
    assert row.downstream_request_missing is True and row.downstream_wait_h is None
    assert row.unmatched_downstream_events == 1
    cursor.advance(
        12, [request(config).model_copy(update={"ingested_h": 12.0, "available_h": 12.0})]
    )
    row = cursor.for_patient(patient(config, 12))
    assert row.downstream_request_missing is False and row.unmatched_downstream_events == 0
    assert row.downstream and isinstance(row.downstream.payload, Downstream)
    assert row.downstream.payload.status == "confirmed"


def test_destination_change_does_not_implicitly_cancel_aval(config: HospitalConfig) -> None:
    cursor = CareAsOfCursor(config)
    cursor.advance(
        10,
        [
            request(config),
            care(
                config, event="DEST", hour=8.0, payload=RequestedDestination(destination="domicile")
            ),
            care(config, event="HELP", hour=9.0, payload=HomeHelp(status="organized")),
        ],
    )
    row = cursor.for_patient(patient(config))
    assert row.downstream_wait_h == 8 and row.home_help


@pytest.mark.parametrize("mutation", ["future", "topology", "identity", "version", "receipt"])
def test_care_batch_validation_is_atomic(config: HospitalConfig, mutation: str) -> None:
    cursor = CareAsOfCursor(config)
    original = care(config)
    cursor.advance(10, [original])
    bad = original.model_copy(update={"delivery_id": "bad"})
    if mutation == "future":
        bad = bad.model_copy(update={"available_h": 100.0})
    elif mutation == "topology":
        bad = bad.model_copy(update={"pole_id": "WRONG"})
    elif mutation == "identity":
        bad = bad.model_copy(update={"event_h": 1.0, "event_version": 2, "replaces_version": 1})
    elif mutation == "version":
        bad = bad.model_copy(
            update={"payload": original.payload.model_copy(update={"minutes_per_24h": 999.0})}
        )
    else:
        bad = bad.model_copy(update={"delivery_id": original.delivery_id, "available_h": 11.0})
    with pytest.raises(ValueError):
        cursor.advance(11, [care(config, event="NEW"), bad])
    assert cursor.hour == 10 and "NEW" not in cursor.history["S1"]


@pytest.mark.parametrize(
    "mutation",
    ["extra_outcome", "negative_charge", "nonfinite", "future_fact", "wrong_mask", "fake_wait"],
)
def test_closed_schema_and_temporal_feature_mutations(
    config: HospitalConfig, mutation: str
) -> None:
    if mutation in ("extra_outcome", "negative_charge", "nonfinite"):
        raw = care(config).model_dump()
        if mutation == "extra_outcome":
            raw["payload"]["actual_departure_h"] = 100
        else:
            raw["payload"]["minutes_per_24h"] = (
                -1.0 if mutation == "negative_charge" else float("nan")
            )
        with pytest.raises(ValueError):
            CareDelivery.model_validate(raw)
    else:
        cursor = CareAsOfCursor(config)
        cursor.advance(10, [care(config)])
        raw = cursor.for_patient(patient(config)).model_dump()
        if mutation == "future_fact":
            raw["assessment"]["available_h"] = 11.0
        elif mutation == "wrong_mask":
            raw["assessment_missing"] = True
        else:
            raw["downstream_wait_h"] = 8.0
        with pytest.raises(ValueError):
            PatientCareRow.model_validate(raw)


def test_care_only_stream_prefix_mutation_and_outages(dataset: tuple[Path, HospitalConfig]) -> None:
    root, config = dataset
    events = list(_events(root / "truth"))
    rows = observe_care(events, config)
    assert rows == observe_care(reversed(events), config)
    assert any(r.event_version > 1 for r in rows)
    assert len(rows) > len({(r.event_id, r.event_version) for r in rows})
    assert all(not 30 <= r.available_h < 66 and not 30 <= r.ingested_h < 66 for r in rows)
    assert any(30 <= r.event_h < 66 and r.available_h >= 66 for r in rows)
    prefix = observe_care((e for e in events if e["h"] < 72), config)
    assert [r for r in rows if r.available_h <= 72] == [r for r in prefix if r.available_h <= 72]
    batches: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        batches[event["h"]].append(event)
    online = OnlineCare(config)
    received: list[CareDelivery] = []
    for hour in range(-config.warmup_days * 24, config.days * 24):
        online.push(hour, batches[hour])
        received.extend(online.receive(hour + 1))
    assert received == rows
    with pytest.raises(ValueError):
        online.receive(config.days * 24 + 1)


def test_source_workflow_ids_do_not_depend_on_receipt_loss(config: HospitalConfig) -> None:
    events = [
        source(config, "DEMANDE_AVAL", {"type_aval": "SMR"}, 1, 1),
        source(config, "PLACE_AVAL_CONFIRMEE", {"type_aval": "SMR"}, 2, 2),
        source(config, "DEMANDE_AVAL_ANNULEE", {}, 3, 3),
    ]
    raw = config.model_dump()
    raw["observation"] = {"mode": "site_v1", "missing_probability": 0.0}
    rows = observe_care(events, HospitalConfig.model_validate(raw))
    assert all(
        isinstance(r.payload, Downstream) and r.payload.request_id == events[0]["event_id"]
        for r in rows
    )


def read_rows(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt") as stream:
        return [json.loads(line) for line in stream]


def test_pipeline_reproducibility_population_and_target_isolation(
    dataset: tuple[Path, HospitalConfig],
) -> None:
    root, config = dataset
    before = hashlib.sha256((root / "truth/manifest.json").read_bytes()).hexdigest()
    profile = CensusProfile()
    enriched = prepare_patient_run(
        root / "truth", root / "care_a", census_profile=profile, with_care=True
    )
    again = prepare_patient_run(
        root / "truth", root / "care_b", census_profile=profile, with_care=True
    )
    assert (
        enriched == again and enriched["counts"]["care_rows"] == enriched["counts"]["features"] > 0
    )
    plain = prepare_patient_run(root / "truth", root / "care_plain", census_profile=profile)
    assert "features/patient_care_asof.jsonl.gz" not in plain["files_sha256"]
    for name in (
        "features/patients_asof.jsonl.gz",
        "targets/departures.jsonl.gz",
        "observed/reconciliation.jsonl.gz",
    ):
        a = read_rows(root / "care_a" / name)
        b = read_rows(root / "care_plain" / name)
        for rows in (a, b):
            for row in rows:
                row.pop("sample_id", None)
                row.pop("run_id", None)
        assert a == b
    for name, digest in enriched["files_sha256"].items():
        assert hashlib.sha256((root / "care_a" / name).read_bytes()).hexdigest() == digest
    assert before == hashlib.sha256((root / "truth/manifest.json").read_bytes()).hexdigest()
    patients = [
        PatientRow.model_validate(r)
        for r in read_rows(root / "care_a/features/patients_asof.jsonl.gz")
    ]
    expected = [
        PatientCareRow.model_validate(r)
        for r in read_rows(root / "care_a/features/patient_care_asof.jsonl.gz")
    ]
    assert (
        list(replay_care(patients, observe_care(_events(root / "truth"), config), config))
        == expected
    )
    assert all(r.sample_id == p.sample_id for r, p in zip(expected, patients, strict=True))
    with pytest.raises(FileExistsError):
        prepare_patient_run(root / "truth", root / "care_a", with_care=True)


def test_care_requires_patient_cohort(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="requires with_patients"):
        cohort.materialize(tmp_path / "missing", tmp_path / "output", with_care=True)
