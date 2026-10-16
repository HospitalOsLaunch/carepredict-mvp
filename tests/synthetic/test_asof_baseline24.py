"""Temporal invariance, revision semantics, missingness and 24h target alignment."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from hospitalos.synthetic.asof import AsOfRow, replay
from hospitalos.synthetic.baseline24 import predict, score
from hospitalos.synthetic.config import HospitalConfig
from hospitalos.synthetic.generate import generate
from hospitalos.synthetic.learning import build_labels, prepare_learning_run, verify_source
from hospitalos.synthetic.observations import Delivery, ObservedState, observe_snapshots

EXAMPLE = Path(__file__).resolve().parents[2] / "configs/synthetic/hospital_two_poles.json"


@pytest.fixture
def config() -> HospitalConfig:
    raw = json.loads(EXAMPLE.read_text())
    raw.update(days=3, warmup_days=3)
    for pole in raw["poles"]:
        pole["units"] = pole["units"][:1]
    return HospitalConfig.model_validate(raw)


def delivery(
    config: HospitalConfig,
    *,
    unit: str | None = None,
    event: str = "E1",
    hour: float = 0.0,
    available: float = 0.5,
    version: int = 1,
    occupied: int = 10,
) -> Delivery:
    unit = unit or config.units[0].unit_id
    values: dict[str, Any] = dict.fromkeys(ObservedState.model_fields, 0)
    values.update(
        lits_ouverts=28,
        lits_occupes=occupied,
        lits_propres_libres=28 - occupied,
        charge_soins_min_h=120.0,
    )
    return Delivery(
        delivery_id=f"{event}v{version}",
        event_id=event,
        event_version=version,
        unit_id=unit,
        hospital_id=config.hospital_id,
        pole_id=config.unit_poles[unit],
        event_h=hour,
        recorded_h=available,
        ingested_h=available,
        available_h=available,
        replaces_version=version - 1 if version > 1 else None,
        values=ObservedState.model_validate(values),
    )


def rows(config: HospitalConfig, deliveries: list[Delivery], end: int = 10) -> list[AsOfRow]:
    return list(replay(deliveries, config, run_id="test", end_h=end))


def first_unit(config: HospitalConfig, result: list[AsOfRow], hour: int) -> AsOfRow:
    return next(
        row for row in result if row.entity_id == config.units[0].unit_id and row.decision_h == hour
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("available_h", -1.0),
        ("ingested_h", -1.0),
        ("recorded_h", -1.0),
        ("event_h", float("nan")),
        ("available_h", float("inf")),
        ("event_version", 0),
        ("event_version", True),
        ("replaces_version", 1),
    ],
)
def test_invalid_delivery_clocks_or_version(
    config: HospitalConfig,
    field: str,
    value: Any,
) -> None:
    raw = delivery(config).model_dump()
    raw[field] = value
    with pytest.raises(ValidationError):
        Delivery.model_validate(raw)


def test_hidden_target_is_not_allowed_in_observations(config: HospitalConfig) -> None:
    raw = delivery(config).model_dump()
    raw["values"]["future_occupancy"] = 42
    with pytest.raises(ValidationError, match="Extra inputs"):
        Delivery.model_validate(raw)


def test_only_delivered_versions_are_visible(config: HospitalConfig) -> None:
    before = delivery(config, occupied=10, available=1.0)
    revision = delivery(config, occupied=7, available=4.0, version=2)
    result = rows(config, [revision, before], end=6)
    assert first_unit(config, result, 0).missing
    at_1, at_3, at_4 = (first_unit(config, result, hour) for hour in (1, 3, 4))
    assert at_1.values and at_1.values.lits_occupes == 10  # equality at cutoff is available
    assert at_3.values and at_3.values.lits_occupes == 10
    assert at_4.values and at_4.values.lits_occupes == 7
    assert at_4.sources[0].version == 2


def test_future_deliveries_cannot_change_past_features_or_predictions(
    config: HospitalConfig,
) -> None:
    past = delivery(config, occupied=10)
    future = delivery(config, occupied=22, available=20.0, version=2)
    left, right = rows(config, [past], end=10), rows(config, [past, future], end=10)
    assert left == right
    assert predict(left) == predict(right)


def test_late_old_revision_does_not_replace_newer_snapshot(config: HospitalConfig) -> None:
    result = rows(
        config,
        [
            delivery(config),
            delivery(config, event="E2", hour=2.0, available=2.5, occupied=15),
            delivery(config, available=4.0, version=2, occupied=5),
        ],
    )
    latest = first_unit(config, result, 4)
    assert latest.values and latest.values.lits_occupes == 15
    assert latest.sources[0].event_id == "E2"


def test_late_v1_does_not_replace_v2(config: HospitalConfig) -> None:
    result = rows(
        config,
        [delivery(config, available=3.0), delivery(config, available=1.0, version=2, occupied=7)],
    )
    latest = first_unit(config, result, 4)
    assert latest.values and latest.values.lits_occupes == 7


def test_retry_is_idempotent_and_does_not_refresh_freshness(config: HospitalConfig) -> None:
    original = delivery(config)
    raw = original.model_dump()
    raw.update(delivery_id="retry", ingested_h=2.0, available_h=2.0)
    retried = Delivery.model_validate(raw)
    assert rows(config, [original]) == rows(config, [retried, original, original])


def test_conflicting_duplicate_rejected(config: HospitalConfig) -> None:
    other = delivery(config, occupied=20).model_dump()
    other["delivery_id"] = "corrupted-retry"
    with pytest.raises(ValueError, match="Conflicting duplicate"):
        rows(config, [delivery(config), Delivery.model_validate(other)])


def test_event_identity_cannot_change(config: HospitalConfig) -> None:
    revision = delivery(config, unit=config.units[1].unit_id, version=2, available=2.0)
    with pytest.raises(ValueError, match="Event identity"):
        rows(config, [delivery(config), revision])


def test_wrong_hospital_rejected(config: HospitalConfig) -> None:
    raw = delivery(config).model_dump()
    raw["hospital_id"] = "OTHER"
    with pytest.raises(ValueError, match="topology"):
        rows(config, [Delivery.model_validate(raw)])


def test_missing_units_are_not_zero_filled(config: HospitalConfig) -> None:
    result = rows(config, [delivery(config)], end=2)
    hospital = next(row for row in result if row.level == "hospital" and row.decision_h == 1)
    assert hospital.missing and hospital.values is None
    assert hospital.observed_units == 1 and hospital.total_units == 2
    prediction = predict([hospital])[0]
    assert prediction["status"] == "missing" and prediction["prediction_lits_occupes"] is None


def test_complete_hospital_sums_available_units(config: HospitalConfig) -> None:
    result = rows(
        config,
        [
            delivery(config),
            delivery(
                config,
                unit=config.units[1].unit_id,
                event="E2",
                occupied=8,
            ),
        ],
    )
    hospital = next(row for row in result if row.level == "hospital" and row.decision_h == 1)
    assert hospital.values and hospital.values.lits_occupes == 18
    assert hospital.values.charge_soins_min_h == 240.0
    assert len(hospital.sources) == 2


def test_stale_snapshot_abstains_without_erasing_history(config: HospitalConfig) -> None:
    result = rows(config, [delivery(config)])
    fresh, stale = first_unit(config, result, 6), first_unit(config, result, 7)
    assert not fresh.stale and stale.stale
    assert stale.values and stale.values.lits_occupes == 10
    assert predict([stale])[0]["prediction_lits_occupes"] is None


@pytest.mark.parametrize("mutation", ["future_source", "filled_missing", "future_column", "age"])
def test_mutated_feature_contract_fails(config: HospitalConfig, mutation: str) -> None:
    result = rows(config, [delivery(config)])
    raw = first_unit(config, result, 1).model_dump()
    if mutation == "future_source":
        raw["sources"][0]["available_h"] = 2.0
    elif mutation == "filled_missing":
        raw["missing"] = True
    elif mutation == "future_column":
        raw["target_lits_occupes"] = 20
    else:
        raw["max_age_h"] = 0
    with pytest.raises(ValidationError):
        AsOfRow.model_validate(raw)


def test_labels_use_end_of_hour_and_censor_the_tail(tmp_path: Path, config: HospitalConfig) -> None:
    truth = tmp_path / "truth"
    truth.mkdir()
    fields = [
        "h",
        "unit_id",
        "hospital_id",
        "pole_id",
        "lits_occupes",
        "attente_urgences_nb",
        "charge_soins_min_h",
    ]
    with (truth / "units_hourly.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for hour in range(config.days * 24):
            for unit in config.units:
                writer.writerow(
                    {
                        "h": hour,
                        "unit_id": unit.unit_id,
                        "hospital_id": config.hospital_id,
                        "pole_id": config.unit_poles[unit.unit_id],
                        "lits_occupes": hour,
                        "attente_urgences_nb": 0,
                        "charge_soins_min_h": hour * 10,
                    }
                )
    labels = build_labels(tmp_path, config, rows(config, [], end=72))
    unit_labels = {label["decision_h"]: label for label in labels if label["level"] == "unit"}
    assert unit_labels[0]["target_h"] == 24
    assert unit_labels[0]["target_lits_occupes"] == 23  # boundary 24 = end of truth row 23
    assert unit_labels[48]["target_lits_occupes"] == 71  # boundary 72 exists
    assert unit_labels[49]["censored"] and unit_labels[49]["target_lits_occupes"] is None


def test_score_reports_errors_and_abstention(config: HospitalConfig) -> None:
    selected = [first_unit(config, rows(config, [delivery(config)]), hour) for hour in (0, 1, 7)]
    predictions = predict(selected)
    labels = [
        {
            **{
                key: pred[key]
                for key in (
                    "sample_id",
                    "entity_id",
                    "level",
                    "hospital_id",
                    "partition",
                    "decision_h",
                    "target_h",
                    "horizon_h",
                )
            },
            "censored": False,
            "target_lits_occupes": 8.0,
            "target_attente_urgences_nb": 0.0,
            "target_charge_soins_min_h": 110.0,
        }
        for pred in predictions
    ]
    report = score(predictions, labels)
    occupancy = next(row for row in report["metrics"] if row["target"] == "lits_occupes")
    assert occupancy["n_scored"] == 1 and occupancy["eligible"] == 3
    assert occupancy["missing"] == 1 and occupancy["stale"] == 1
    assert occupancy["coverage"] == pytest.approx(1 / 3)
    assert occupancy["mae"] == occupancy["rmse"] == occupancy["bias"] == 2.0
    altered = deepcopy(labels)
    altered[1]["target_lits_occupes"] = 100.0
    assert predict(selected) == predictions  # labels never enter predict()
    assert score(predictions, altered) != report
    altered[1]["target_h"] += 1
    with pytest.raises(ValueError, match="mismatch"):
        score(predictions, altered)


@pytest.fixture(scope="module")
def pipeline_runs(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, Path, Path, HospitalConfig]:
    raw = json.loads(EXAMPLE.read_text())
    raw.update(days=3, warmup_days=3)
    config = HospitalConfig.model_validate(raw)
    root = tmp_path_factory.mktemp("asof-runs")
    source, first, second = root / "truth", root / "first", root / "second"
    generate(config, source)
    prepare_learning_run(source, first)
    prepare_learning_run(source, second)
    return source, first, second, config


def test_pipeline_is_byte_reproducible(
    pipeline_runs: tuple[Path, Path, Path, HospitalConfig],
) -> None:
    source, first, second, config = pipeline_runs
    for path in first.rglob("*"):
        if path.is_file():
            assert path.read_bytes() == (second / path.relative_to(first)).read_bytes()
    manifest = json.loads((first / "manifest.json").read_text())
    for name, digest in manifest["files_sha256"].items():
        assert hashlib.sha256((first / name).read_bytes()).hexdigest() == digest
    assert manifest["counts"]["features"] == 72 * 7
    assert verify_source(source)[0] == config


def test_adapter_clock_and_closed_payload(
    pipeline_runs: tuple[Path, Path, Path, HospitalConfig],
) -> None:
    source, first, _, config = pipeline_runs
    with gzip.open(source / "truth/events.jsonl.gz", "rt") as stream:
        truth = [json.loads(line) for line in stream]
    states = {row["event_id"]: row for row in truth if row["type"] == "ETAT_UNITE"}
    with gzip.open(first / "observed/unit_states.jsonl.gz", "rt") as stream:
        deliveries = [Delivery.model_validate_json(line) for line in stream]
    assert deliveries == observe_snapshots(reversed(truth), config)
    for row in deliveries:
        assert row.event_h == states[row.event_id]["h"] + 1
        assert row.event_h <= row.available_h <= config.days * 24
        assert set(row.values.model_dump()) == set(ObservedState.model_fields)
    with gzip.open(first / "features/asof.jsonl.gz", "rt") as stream:
        for line in stream:
            feature = AsOfRow.model_validate_json(line)
            assert all(item.available_h <= feature.decision_h for item in feature.sources)


def test_source_corruption_and_output_overwrite_rejected(
    pipeline_runs: tuple[Path, Path, Path, HospitalConfig],
    tmp_path: Path,
) -> None:
    source, first, _, _ = pipeline_runs
    with pytest.raises(FileExistsError):
        prepare_learning_run(source, first)
    with pytest.raises(ValueError, match="outside"):
        prepare_learning_run(source, source / "nested-output")
    # Mutate an independent copy of the source manifest, not the shared fixture.
    (tmp_path / "config.json").write_bytes((source / "config.json").read_bytes() + b" ")
    (tmp_path / "manifest.json").write_bytes((source / "manifest.json").read_bytes())
    with pytest.raises(ValueError, match="checksum"):
        prepare_learning_run(tmp_path, tmp_path.parent / "should-not-exist")


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "fractional_hour"])
def test_corrupted_truth_snapshot_grid_rejected(
    pipeline_runs: tuple[Path, Path, Path, HospitalConfig],
    mutation: str,
) -> None:
    source, _, _, config = pipeline_runs
    with gzip.open(source / "truth/events.jsonl.gz", "rt") as stream:
        events = [json.loads(line) for line in stream]
    index = next(i for i, event in enumerate(events) if event["type"] == "ETAT_UNITE")
    if mutation == "missing":
        events.pop(index)
    elif mutation == "duplicate":
        events.append({**events[index], "event_id": "different-id-same-unit-hour"})
    else:
        events[index]["h"] += 0.5
    with pytest.raises(ValueError, match="snapshot"):
        observe_snapshots(events, config)
