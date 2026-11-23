"""Endpoint semantics and bitemporal labels, with no real hospital data."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from hospitalos.hybrid.learning_demo import protocol, synthetic_records
from hospitalos.hybrid.preparation import PreparationFeatures
from hospitalos.hybrid.retrospective import (
    Followup,
    Landmark,
    PreparationEvent,
    RetrospectiveBatch,
    audit,
    demo_batch,
    synthetic_record,
)
from hospitalos.hybrid.survival import partition


def fixture() -> RetrospectiveBatch:
    at = protocol().train.start
    m = Landmark(
        hospital_id="fictional-hospital",
        patient_id="p",
        episode_id="e",
        unit_id="medicine",
        source="mapped-preparation-feed",
        mapping_version="fictional-v1",
        provenance="synthetic_fixture",
        origin=at,
        snapshot_available_at=at,
        eligible_at_origin=True,
        features=PreparationFeatures(
            occupied_per_staffed_bed=1,
            waiting_per_staffed_bed=1,
            hour_utc=at.hour,
            weekday_utc=at.weekday(),
        ),
        followup=Followup(
            from_at=at,
            through=at + timedelta(days=1),
            available_at=at + timedelta(days=1),
            complete=True,
        ),
    )
    pending = PreparationEvent(
        record_id="pending-r1",
        event_id="pending",
        hospital_id=m.hospital_id,
        patient_id=m.patient_id,
        episode_id=m.episode_id,
        source=m.source,
        kind="pending",
        occurred_at=at,
        available_at=at,
    )
    complete = pending.model_copy(
        update={
            "record_id": "complete-r1",
            "event_id": "complete",
            "kind": "completed",
            "occurred_at": at + timedelta(minutes=60),
            "available_at": at + timedelta(minutes=65),
        }
    )
    return RetrospectiveBatch(protocol=protocol(), landmarks=(m,), events=(pending, complete))


def test_completion_endpoint_is_not_actual_departure() -> None:
    batch = fixture()
    depart = batch.events[1].model_copy(
        update={
            "record_id": "depart-r1",
            "event_id": "depart",
            "kind": "departed",
            "occurred_at": batch.landmarks[0].origin + timedelta(minutes=180),
            "available_at": batch.landmarks[0].origin + timedelta(minutes=181),
        }
    )
    result = audit(batch.model_copy(update={"events": (*batch.events, depart)}))
    assert result.outcomes[0].followed_seconds == 3600
    assert synthetic_record(result.outcomes[0]).followed_minutes == 60
    assert result.real_training_approved is False


def test_actual_departure_without_preparation_is_not_a_target_or_censor() -> None:
    batch = fixture()
    depart = batch.events[1].model_copy(update={"kind": "departed"})
    result = audit(batch.model_copy(update={"events": (batch.events[0], depart)}))
    assert not result.outcomes
    assert result.exclusions_by_reason == {"departure_without_preparation_endpoint": 1}


@pytest.mark.parametrize("kind", ["cancelled", "eligibility_revoked", "death", "transferred"])
def test_competing_events_before_completion_require_adjudication(kind: str) -> None:
    batch = fixture()
    competing = batch.events[1].model_copy(
        update={
            "record_id": "other-r1",
            "event_id": "other",
            "kind": kind,
            "occurred_at": batch.landmarks[0].origin + timedelta(minutes=30),
        }
    )
    result = audit(batch.model_copy(update={"events": (*batch.events, competing)}))
    assert result.exclusions_by_reason == {"competing_event_requires_adjudication": 1}


def test_cotimed_completion_and_departure_are_allowed_but_cotimed_death_is_not() -> None:
    batch = fixture()
    other = batch.events[1].model_copy(
        update={"record_id": "other-r1", "event_id": "other", "kind": "departed"}
    )
    assert audit(batch.model_copy(update={"events": (*batch.events, other)})).outcomes
    other = other.model_copy(update={"kind": "death"})
    assert not audit(batch.model_copy(update={"events": (*batch.events, other)})).outcomes


def test_silence_requires_attested_continuous_followup() -> None:
    batch = fixture().model_copy(update={"events": fixture().events[:1]})
    result = audit(batch)
    assert result.outcomes[0].status == "right_censored"
    assert result.outcomes[0].followed_seconds == 86400
    m = batch.landmarks[0].model_copy(update={"followup": None})
    assert audit(batch.model_copy(update={"landmarks": (m,)})).exclusions_by_reason == {
        "continuous_followup_not_confirmed": 1
    }


@pytest.mark.parametrize("fault", ["gap", "unconfirmed", "late"])
def test_incomplete_or_late_followup_is_excluded(fault: str) -> None:
    batch = fixture()
    m = batch.landmarks[0]
    assert m.followup is not None
    changes: dict[str, dict[str, object]] = {
        "gap": {"from_at": m.origin + timedelta(minutes=1)},
        "unconfirmed": {"complete": False},
        "late": {"available_at": batch.protocol.train.labels_available_by + timedelta(minutes=1)},
    }
    m = m.model_copy(update={"followup": m.followup.model_copy(update=changes[fault])})
    assert not audit(batch.model_copy(update={"landmarks": (m,)})).outcomes


@pytest.mark.parametrize("fault", ["future_snapshot", "unknown_eligibility", "no_pending"])
def test_landmark_is_built_only_from_eligible_observed_pending_state(fault: str) -> None:
    batch = fixture()
    m = batch.landmarks[0]
    if fault == "future_snapshot":
        batch = batch.model_copy(
            update={
                "landmarks": (
                    m.model_copy(update={"snapshot_available_at": m.origin + timedelta(minutes=1)}),
                )
            }
        )
    elif fault == "unknown_eligibility":
        batch = batch.model_copy(
            update={"landmarks": (m.model_copy(update={"eligible_at_origin": None}),)}
        )
    else:
        batch = batch.model_copy(update={"events": batch.events[1:]})
    assert not audit(batch).outcomes


def test_revision_changes_label_only_if_available_at_partition_cutoff() -> None:
    batch = fixture()
    correction = batch.events[1].model_copy(
        update={
            "record_id": "complete-r2",
            "revision": 2,
            "occurred_at": batch.landmarks[0].origin + timedelta(minutes=120),
            "available_at": batch.protocol.train.labels_available_by + timedelta(seconds=1),
        }
    )
    assert (
        audit(batch.model_copy(update={"events": (*batch.events, correction)}))
        .outcomes[0]
        .followed_seconds
        == 3600
    )
    correction = correction.model_copy(
        update={"available_at": batch.protocol.train.labels_available_by}
    )
    outcome = audit(batch.model_copy(update={"events": (*batch.events, correction)})).outcomes[0]
    assert outcome.followed_seconds == 7200
    assert outcome.known_by == batch.protocol.train.labels_available_by


def test_late_evidence_before_origin_excludes_instead_of_leaking_into_features() -> None:
    batch = fixture()
    completion = batch.events[1].model_copy(
        update={"occurred_at": batch.landmarks[0].origin - timedelta(minutes=1)}
    )
    result = audit(batch.model_copy(update={"events": (batch.events[0], completion)}))
    assert result.exclusions_by_reason == {"late_evidence_invalidates_origin": 1}


def test_retracted_completion_does_not_turn_into_censoring_and_restoration_is_visible() -> None:
    batch = fixture()
    retracted = batch.events[1].model_copy(
        update={
            "record_id": "complete-r2",
            "revision": 2,
            "retracted": True,
            "available_at": batch.landmarks[0].origin + timedelta(minutes=90),
        }
    )
    revised = batch.model_copy(update={"events": (*batch.events, retracted)})
    assert audit(revised).exclusions_by_reason == {"retracted_event_requires_adjudication": 1}
    restored = retracted.model_copy(
        update={
            "record_id": "complete-r3",
            "revision": 3,
            "retracted": False,
            "available_at": batch.landmarks[0].origin + timedelta(minutes=100),
        }
    )
    assert (
        audit(revised.model_copy(update={"events": (*revised.events, restored)})).outcomes[0].status
        == "completed"
    )


def test_revision_conflict_or_wrong_source_fails_closed() -> None:
    batch = fixture()
    duplicate = batch.events[1].model_copy(update={"record_id": "conflict"})
    assert audit(
        batch.model_copy(update={"events": (*batch.events, duplicate)})
    ).exclusions_by_reason == {"conflicting_event_revisions": 1}
    other = batch.events[1].model_copy(update={"source": "another-feed"})
    assert audit(
        batch.model_copy(update={"events": (batch.events[0], other)})
    ).exclusions_by_reason == {"unexpected_event_source": 1}


def test_late_conflicting_source_does_not_change_frozen_label() -> None:
    batch = fixture()
    future = batch.events[1].model_copy(
        update={
            "record_id": "future-record",
            "source": "another-feed",
            "available_at": batch.protocol.train.labels_available_by + timedelta(seconds=1),
        }
    )
    assert audit(batch.model_copy(update={"events": (*batch.events, future)})) == audit(batch)


@pytest.mark.parametrize("minute,observed", [(1440, True), (1441, False)])
def test_24_hour_boundary_preserves_tail(minute: int, observed: bool) -> None:
    batch = fixture()
    event = batch.events[1].model_copy(
        update={
            "occurred_at": batch.landmarks[0].origin + timedelta(minutes=minute),
            "available_at": batch.landmarks[0].origin + timedelta(minutes=minute),
        }
    )
    result = audit(batch.model_copy(update={"events": (batch.events[0], event)}))
    outcome = synthetic_record(result.outcomes[0])
    assert outcome.followed_minutes == 1440
    assert outcome.event_observed is observed


def test_observed_records_and_subminute_endpoints_cannot_enter_synthetic_training() -> None:
    batch = fixture()
    m = batch.landmarks[0].model_copy(update={"provenance": "observed_unvalidated"})
    result = audit(batch.model_copy(update={"landmarks": (m,)}))
    with pytest.raises(ValueError, match="does not authorize"):
        synthetic_record(result.outcomes[0])
    event = batch.events[1].model_copy(
        update={"occurred_at": batch.landmarks[0].origin + timedelta(seconds=31)}
    )
    result = audit(batch.model_copy(update={"events": (batch.events[0], event)}))
    assert result.outcomes[0].followed_seconds == 31
    with pytest.raises(ValueError, match="discretization"):
        synthetic_record(result.outcomes[0])


def test_episode_patient_identity_cannot_cross_partitions_or_hospitals() -> None:
    batch = fixture()
    duplicate = batch.landmarks[0].model_copy(update={"episode_id": "another-episode"})
    with pytest.raises(ValidationError, match="One landmark"):
        RetrospectiveBatch.model_validate(
            {**batch.model_dump(), "landmarks": (*batch.landmarks, duplicate)}
        )
    event = batch.events[1].model_copy(update={"hospital_id": "another-hospital"})
    with pytest.raises(ValidationError, match="no matching"):
        RetrospectiveBatch.model_validate(
            {**batch.model_dump(), "events": (batch.events[0], event)}
        )


def test_future_occurrence_is_not_an_observed_event() -> None:
    batch = fixture()
    event = batch.events[0]
    with pytest.raises(ValidationError, match="Only observed events"):
        PreparationEvent.model_validate(
            {**event.model_dump(), "occurred_at": event.available_at + timedelta(seconds=1)}
        )


def test_full_synthetic_event_to_label_to_temporal_partition_roundtrip() -> None:
    split = protocol()
    records = synthetic_records(split, counts=(60, 20, 20, 30))
    landmarks, events = [], []
    for r in records:
        landmarks.append(
            Landmark(
                hospital_id=r.hospital_id,
                patient_id=r.patient_id,
                episode_id=r.episode_id,
                unit_id=r.unit_id,
                source="synthetic-events",
                mapping_version="fictional-v1",
                provenance="synthetic_fixture",
                origin=r.origin,
                snapshot_available_at=r.features_available_at,
                eligible_at_origin=True,
                features=r.features,
                followup=Followup(
                    from_at=r.origin,
                    through=r.origin + timedelta(minutes=r.followed_minutes),
                    available_at=r.label_available_at,
                    complete=True,
                ),
            )
        )
        pending = PreparationEvent(
            record_id=f"{r.episode_id}:pending",
            event_id=f"{r.episode_id}:pending",
            hospital_id=r.hospital_id,
            patient_id=r.patient_id,
            episode_id=r.episode_id,
            source="synthetic-events",
            kind="pending",
            occurred_at=r.origin,
            available_at=r.origin,
        )
        events.append(pending)
        if r.event_observed:
            events.append(
                pending.model_copy(
                    update={
                        "record_id": f"{r.episode_id}:complete",
                        "event_id": f"{r.episode_id}:complete",
                        "kind": "completed",
                        "occurred_at": r.origin + timedelta(minutes=r.followed_minutes),
                        "available_at": r.label_available_at,
                    }
                )
            )
    batch = RetrospectiveBatch(protocol=split, landmarks=tuple(landmarks), events=tuple(events))
    result = audit(RetrospectiveBatch.model_validate_json(batch.model_dump_json()))
    assert not result.exclusions
    rebuilt = tuple(synthetic_record(outcome) for outcome in result.outcomes)
    assert partition(rebuilt, split) == partition(records, split)
    assert result.counts_by_partition == {
        "train": 60,
        "calibration": 20,
        "validation": 20,
        "test": 30,
    }


def test_cli_audits_json_demo_without_emitting_patient_rows(tmp_path: Path) -> None:
    batch = demo_batch()
    path = tmp_path / "batch.json"
    path.write_text(batch.model_dump_json())
    process = subprocess.run(
        [sys.executable, "-m", "hospitalos.hybrid.retrospective", "--input", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    result = json.loads(process.stdout)
    assert result["exclusions_by_reason"] == {"departure_without_preparation_endpoint": 1}
    assert sum(result["counts_by_partition"].values()) == 23
    assert "outcomes" not in result and "exclusions" not in result
    assert batch.landmarks[0].patient_id not in process.stdout


def test_cli_invalid_input_does_not_echo_source_values(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text('{"unrecognized": "PRIVATE_SOURCE_VALUE"}')
    process = subprocess.run(
        [sys.executable, "-m", "hospitalos.hybrid.retrospective", "--input", str(path)],
        capture_output=True,
        text=True,
    )
    assert process.returncode == 2
    assert "PRIVATE_SOURCE_VALUE" not in process.stdout + process.stderr
