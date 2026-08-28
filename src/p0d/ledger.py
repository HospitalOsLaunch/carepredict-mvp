"""Append-only bitemporal ledger, snapshots, replay, and freshness."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from .canonical import CanonicalEvent, canonical_json_bytes, utc_datetime, utc_text


class LedgerError(ValueError):
    """An append or snapshot would violate the P-0D ledger contract."""


def semantic_deduplicate(events: tuple[CanonicalEvent, ...]) -> tuple[CanonicalEvent, ...]:
    """Collapse transport retries while preserving the earliest known assertion."""

    correction_targets = {
        event.correction_of for event in events if event.correction_of is not None
    }
    selected: dict[tuple[object, ...], CanonicalEvent] = {}
    for event in sorted(events, key=lambda item: item.replay_key()):
        key = event.semantic_key()
        current = selected.get(key)
        if current is None or (
            current.event_id not in correction_targets and event.event_id in correction_targets
        ):
            selected[key] = event
    return tuple(sorted(selected.values(), key=lambda item: item.replay_key()))


@dataclass(frozen=True, slots=True)
class Snapshot:
    as_of: datetime
    events: tuple[CanonicalEvent, ...]
    snapshot_id: str

    @classmethod
    def build(cls, as_of: datetime, events: tuple[CanonicalEvent, ...]) -> Snapshot:
        normalized = utc_datetime(as_of, "as_of")
        manifest = {
            "as_of": utc_text(normalized),
            "events": [event.manifest_record() for event in events],
        }
        return cls(
            as_of=normalized,
            events=events,
            snapshot_id=hashlib.sha256(canonical_json_bytes(manifest)).hexdigest(),
        )

    def manifest(self) -> dict[str, object]:
        return {
            "schema": "hospitalos.p0d.snapshot-manifest/1",
            "snapshot_id": self.snapshot_id,
            "as_of": utc_text(self.as_of),
            "events": [event.manifest_record() for event in self.events],
        }


@dataclass(frozen=True, slots=True)
class ObservationProcess:
    event_type: str
    site_id: str
    unit_id: str
    observed_count: int
    late_arrival_count: int
    last_event_time: datetime
    last_available_at: datetime
    event_age_seconds: int
    availability_lag_seconds: int
    stale: bool


@dataclass(frozen=True, slots=True)
class EventLedger:
    """Persistent-value ledger: append returns a new ledger and never rewrites history."""

    events: tuple[CanonicalEvent, ...] = ()

    def append(self, event: CanonicalEvent) -> EventLedger:
        by_id = {item.event_id: item for item in self.events}
        if event.event_id in by_id:
            raise LedgerError(f"duplicate event_id: {event.event_id}")
        if event.correction_of is not None:
            target = by_id.get(event.correction_of)
            if target is None:
                raise LedgerError("correction target must already exist in the ledger")
            identity = (
                "event_type",
                "entity_type",
                "entity_id",
                "source_system",
                "site_id",
                "unit_id",
                "event_time",
            )
            if any(getattr(event, field) != getattr(target, field) for field in identity):
                raise LedgerError("a correction must preserve target identity and event time")
            if (
                event.recorded_at < target.recorded_at
                or event.available_at < target.available_at
                or event.ingested_at < target.ingested_at
            ):
                raise LedgerError("a correction cannot precede the assertion it corrects")
        return EventLedger((*self.events, event))

    def extend(self, events: tuple[CanonicalEvent, ...]) -> EventLedger:
        ledger = self
        for event in events:
            ledger = ledger.append(event)
        return ledger

    def replay(self, as_of: datetime) -> tuple[CanonicalEvent, ...]:
        """Replay only facts observable by ``as_of`` in a total stable order."""

        normalized = utc_datetime(as_of, "as_of")
        eligible = tuple(
            event
            for event in self.events
            if event.event_time <= normalized and event.available_at <= normalized
        )
        unique = semantic_deduplicate(eligible)
        superseded = {event.correction_of for event in unique if event.correction_of is not None}
        active = tuple(event for event in unique if event.event_id not in superseded)
        return tuple(sorted(active, key=lambda item: item.replay_key()))

    def snapshot(self, as_of: datetime) -> Snapshot:
        normalized = utc_datetime(as_of, "as_of")
        return Snapshot.build(normalized, self.replay(normalized))

    def observation_process(
        self, as_of: datetime, *, stale_after: timedelta
    ) -> tuple[ObservationProcess, ...]:
        if stale_after <= timedelta(0):
            raise LedgerError("stale_after must be positive")
        normalized = utc_datetime(as_of, "as_of")
        grouped: dict[tuple[str, str, str], list[CanonicalEvent]] = {}
        for event in self.replay(normalized):
            grouped.setdefault((event.event_type, event.site_id, event.unit_id), []).append(event)
        results: list[ObservationProcess] = []
        for (event_type, site_id, unit_id), events in sorted(grouped.items()):
            last_event_time = max(event.event_time for event in events)
            last_available_at = max(event.available_at for event in events)
            results.append(
                ObservationProcess(
                    event_type=event_type,
                    site_id=site_id,
                    unit_id=unit_id,
                    observed_count=len(events),
                    late_arrival_count=sum(
                        event.available_at > event.event_time for event in events
                    ),
                    last_event_time=last_event_time,
                    last_available_at=last_available_at,
                    event_age_seconds=int((normalized - last_event_time).total_seconds()),
                    availability_lag_seconds=int(
                        (last_available_at - last_event_time).total_seconds()
                    ),
                    stale=normalized - last_event_time > stale_after,
                )
            )
        return tuple(results)
