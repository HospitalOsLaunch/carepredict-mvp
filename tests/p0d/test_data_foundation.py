from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from p0d import (
    CanonicalEvent,
    CanonicalEventError,
    EventLedger,
    SplitConfig,
    build_dataset,
    canonical_json_bytes,
    semantic_deduplicate,
)


def _time(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, minute, tzinfo=UTC)


def _event(
    event_id: str,
    *,
    event_time: datetime,
    available_at: datetime | None = None,
    ingested_at: datetime | None = None,
    recorded_at: datetime | None = None,
    payload_value: int = 1,
    organization_id: str = "org-1",
    site_id: str = "site-1",
    unit_id: str = "unit-1",
    episode_id: str = "episode-1",
    correction_of: str | None = None,
    lineage: tuple[str, ...] = ("source:synthetic",),
) -> CanonicalEvent:
    available = available_at or event_time
    ingested = ingested_at or available
    return CanonicalEvent.create(
        event_id=event_id,
        event_type="occupancy_observed",
        entity_type="care_episode",
        entity_id=episode_id,
        source_system="synthetic-test",
        site_id=site_id,
        unit_id=unit_id,
        event_time=event_time,
        recorded_at=recorded_at or available,
        available_at=available,
        ingested_at=ingested,
        schema_version=1,
        correction_of=correction_of,
        lineage=lineage,
        payload={
            "organization_id": organization_id,
            "episode_id": episode_id,
            "value": payload_value,
        },
    )


def test_deterministic_dataset_build() -> None:
    events = tuple(
        _event(
            f"event-{index}",
            event_time=_time(index),
            episode_id=f"episode-{index // 3}",
            payload_value=index,
        )
        for index in range(9)
    )
    first_snapshot = EventLedger().extend(events).snapshot(_time(12))
    second_snapshot = EventLedger().extend(tuple(reversed(events))).snapshot(_time(12))
    config = SplitConfig(seed="fixed-seed", holdout_level="episode")
    first = build_dataset(first_snapshot, split_config=config, window_size=2)
    second = build_dataset(second_snapshot, split_config=config, window_size=2)

    assert first.snapshot_id == second.snapshot_id
    assert first.dataset_id == second.dataset_id
    assert canonical_json_bytes(first.manifest) == canonical_json_bytes(second.manifest)
    assert first.manifest["dataset_id"] == first.dataset_id


def test_temporal_leakage_and_future_observation() -> None:
    future_available = _event(
        "future-available",
        event_time=_time(1),
        available_at=_time(5),
        ingested_at=_time(5),
    )
    future_event = _event(
        "future-event",
        event_time=_time(6),
        recorded_at=_time(2),
        available_at=_time(2),
        ingested_at=_time(2),
    )
    visible = _event("visible", event_time=_time(1), available_at=_time(2))
    snapshot = EventLedger().extend((future_event, future_available, visible)).snapshot(_time(3))

    assert [event.event_id for event in snapshot.events] == ["visible"]
    assert all(event.available_at <= snapshot.as_of for event in snapshot.events)
    assert all(event.event_time <= snapshot.as_of for event in snapshot.events)


def test_split_before_windowing() -> None:
    events = tuple(
        _event(
            f"{episode}-{index}",
            event_time=_time(index),
            organization_id=f"org-{episode % 2}",
            site_id=f"site-{episode % 3}",
            unit_id=f"unit-{episode % 4}",
            episode_id=f"episode-{episode}",
            payload_value=index,
        )
        for episode in range(8)
        for index in range(4)
    )
    build = build_dataset(
        EventLedger().extend(events).snapshot(_time(12)),
        split_config=SplitConfig(seed="hierarchy-test", holdout_level="episode"),
        window_size=3,
        stride=1,
    )
    event_split = {item.event.event_id: item.split for item in build.assigned_events}
    event_episode = {
        item.event.event_id: item.hierarchy.episode_id for item in build.assigned_events
    }
    episode_splits: dict[str, set[str]] = {}
    for item in build.assigned_events:
        episode_splits.setdefault(item.hierarchy.episode_id, set()).add(item.split)

    assert all(len(splits) == 1 for splits in episode_splits.values())
    assert build.windows
    for window in build.windows:
        assert {event_split[event_id] for event_id in window.event_ids} == {window.split}
        assert {event_episode[event_id] for event_id in window.event_ids} == {
            window.hierarchy.episode_id
        }


def test_semantic_deduplication() -> None:
    original = _event("transport-a", event_time=_time(1), available_at=_time(2))
    retry = _event(
        "transport-b",
        event_time=_time(1),
        available_at=_time(3),
        ingested_at=_time(3),
    )
    distinct = _event(
        "distinct",
        event_time=_time(1),
        available_at=_time(3),
        ingested_at=_time(3),
        payload_value=2,
    )

    deduplicated = semantic_deduplicate((retry, distinct, original))
    assert [event.event_id for event in deduplicated] == ["transport-a", "distinct"]
    snapshot = EventLedger().extend((retry, distinct, original)).snapshot(_time(4))
    assert [event.event_id for event in snapshot.events] == ["transport-a", "distinct"]


def test_snapshot_identity() -> None:
    events = (
        _event("b", event_time=_time(2)),
        _event("a", event_time=_time(1)),
    )
    first = EventLedger().extend(events).snapshot(_time(4))
    second = EventLedger().extend(tuple(reversed(events))).snapshot(_time(4))

    assert first.snapshot_id == second.snapshot_id
    assert first.manifest() == second.manifest()
    assert [event.event_id for event in first.events] == ["a", "b"]


def test_late_arrival_and_observation_freshness() -> None:
    late = _event(
        "late",
        event_time=_time(1),
        available_at=_time(5),
        ingested_at=_time(6),
    )
    ledger = EventLedger().append(late)

    assert ledger.snapshot(_time(4)).events == ()
    assert [event.event_id for event in ledger.snapshot(_time(5)).events] == ["late"]
    process = ledger.observation_process(_time(8), stale_after=timedelta(hours=6))[0]
    assert process.observed_count == 1
    assert process.late_arrival_count == 1
    assert process.availability_lag_seconds == 4 * 60 * 60
    assert process.event_age_seconds == 7 * 60 * 60
    assert process.stale is True


def test_correction_replay() -> None:
    original = _event("original", event_time=_time(1), payload_value=1)
    correction = _event(
        "correction",
        event_time=_time(1),
        recorded_at=_time(4),
        available_at=_time(5),
        ingested_at=_time(5),
        payload_value=2,
        correction_of="original",
    )
    ledger = EventLedger().append(original).append(correction)

    assert [event.event_id for event in ledger.replay(_time(4))] == ["original"]
    assert [event.event_id for event in ledger.replay(_time(5))] == ["correction"]
    assert ledger.events == (original, correction)
    with pytest.raises(ValueError, match="target"):
        EventLedger().append(correction)

    transport_retry = _event("retry", event_time=_time(1), payload_value=1)
    retry_correction = _event(
        "retry-correction",
        event_time=_time(1),
        recorded_at=_time(6),
        available_at=_time(6),
        ingested_at=_time(6),
        payload_value=3,
        correction_of="retry",
    )
    retry_ledger = EventLedger().extend((original, transport_retry, retry_correction))
    assert [event.event_id for event in retry_ledger.replay(_time(7))] == ["retry-correction"]


def test_timezone_and_dst() -> None:
    paris = ZoneInfo("Europe/Paris")
    first_fold = datetime(2026, 10, 25, 2, 30, tzinfo=paris, fold=0)
    second_fold = datetime(2026, 10, 25, 2, 30, tzinfo=paris, fold=1)
    first = _event("dst-first", event_time=first_fold)
    second = _event("dst-second", event_time=second_fold)

    assert first.event_time.tzinfo is UTC
    assert second.event_time.tzinfo is UTC
    assert first.event_time == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    assert second.event_time == datetime(2026, 10, 25, 1, 30, tzinfo=UTC)
    assert first.event_time != second.event_time
    with pytest.raises(CanonicalEventError, match="timezone-aware"):
        _event("naive", event_time=datetime(2026, 1, 1, 1))


def test_sql_append_only_contract() -> None:
    sql_path = (
        Path(__file__).resolve().parents[2]
        / "infrastructure/timescaledb/init/05_p0d_bitemporal.sql"
    )
    sql = sql_path.read_text(encoding="utf-8")
    for column in (
        "event_id",
        "event_type",
        "entity_type",
        "entity_id",
        "source_system",
        "site_id",
        "unit_id",
        "event_time",
        "recorded_at",
        "available_at",
        "ingested_at",
        "schema_version",
        "correction_of",
        "payload_hash",
        "lineage",
        "payload",
    ):
        assert column in sql
    assert "BEFORE UPDATE OR DELETE" in sql
    assert "BEFORE TRUNCATE" in sql
    assert "BEFORE INSERT" in sql
    assert "REVOKE UPDATE, DELETE, TRUNCATE" in sql
