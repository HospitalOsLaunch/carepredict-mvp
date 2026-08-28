"""Immutable in-memory contracts for the first-party HFWM-R0 fixture corpus."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from hfwm.contracts import DOSRecord, HDBBenchmark, HDCEpisode, SASRelease
from hfwm.evaluation.splits import Episode, EvaluationWindow, SplitAssignment
from hfwm.htl import HTLRegistry
from p0d import CanonicalEvent, EventLedger, Snapshot, canonical_json_bytes, thaw_json, utc_text

SOURCE_ID = "hfwm_r0_internal_synthetic_fixture"
CORPUS_SCHEMA = "hfwm.r0.internal-synthetic-corpus.v1"
BUILD_CODE_VERSION = "hfwm-r0-temporal-corpus.v1"


@dataclass(frozen=True, slots=True)
class CorpusConfig:
    """Closed deterministic fixture parameters; no pseudo-random state is used."""

    organization_count: int = 3
    sites_per_organization: int = 1
    units_per_site: int = 1
    episodes_per_unit: int = 20
    episode_hours: int = 432
    purge_gap_hours: int = 168
    history_hours: int = 336
    horizons_hours: tuple[int, ...] = (6, 24, 72)
    window_stride_hours: int = 6
    start_at: datetime = datetime(2024, 1, 1, tzinfo=UTC)

    def __post_init__(self) -> None:
        integer_fields = (
            self.organization_count,
            self.sites_per_organization,
            self.units_per_site,
            self.episodes_per_unit,
            self.episode_hours,
            self.purge_gap_hours,
            self.history_hours,
            self.window_stride_hours,
        )
        if any(type(value) is not int or value < 1 for value in integer_fields):
            raise ValueError("corpus dimensions and temporal spans must be positive integers")
        if self.organization_count < 2:
            raise ValueError("the fixture must contain multiple pseudo-organizations")
        if self.episodes_per_unit < 3:
            raise ValueError("each synthetic unit requires train/validation/test episodes")
        if not self.horizons_hours or any(
            type(value) is not int or value < 1 for value in self.horizons_hours
        ):
            raise ValueError("horizons_hours must contain positive integers")
        if self.episode_hours <= self.history_hours + max(self.horizons_hours):
            raise ValueError("episode_hours must permit at least one evaluation window")
        if self.start_at.tzinfo is None or self.start_at.utcoffset() is None:
            raise ValueError("start_at must be timezone-aware")
        object.__setattr__(self, "start_at", self.start_at.astimezone(UTC))
        object.__setattr__(self, "horizons_hours", tuple(sorted(set(self.horizons_hours))))

    def to_dict(self) -> dict[str, object]:
        return {
            "organization_count": self.organization_count,
            "sites_per_organization": self.sites_per_organization,
            "units_per_site": self.units_per_site,
            "episodes_per_unit": self.episodes_per_unit,
            "episode_hours": self.episode_hours,
            "purge_gap_hours": self.purge_gap_hours,
            "history_hours": self.history_hours,
            "horizons_hours": list(self.horizons_hours),
            "window_stride_hours": self.window_stride_hours,
            "start_at": utc_text(self.start_at),
        }


@dataclass(frozen=True, slots=True)
class RecordingInterval:
    """One explicit interval in which the operational observation source is silent."""

    organization_id: str
    site_id: str
    unit_id: str
    episode_id: str
    start_at: datetime
    end_at: datetime
    expected_event_type: str

    def to_dict(self) -> dict[str, object]:
        return {
            "organization_id": self.organization_id,
            "site_id": self.site_id,
            "unit_id": self.unit_id,
            "episode_id": self.episode_id,
            "start_at": utc_text(self.start_at),
            "end_at": utc_text(self.end_at),
            "expected_event_type": self.expected_event_type,
        }


@dataclass(frozen=True, slots=True)
class TemporalCorpus:
    """Complete in-memory corpus and its persisted-contract projections."""

    config: CorpusConfig
    source_id: str
    events: tuple[CanonicalEvent, ...]
    ledger: EventLedger
    episodes: tuple[Episode, ...]
    assignments: tuple[SplitAssignment, ...]
    windows: tuple[EvaluationWindow, ...]
    silent_intervals: tuple[RecordingInterval, ...]
    htl_registry: HTLRegistry
    hdc_episodes: tuple[HDCEpisode, ...]
    hdb_benchmark: HDBBenchmark
    dos_records: tuple[DOSRecord, ...]
    sas_releases: tuple[SASRelease, ...]
    manifest: Mapping[str, object]
    corpus_hash: str

    def snapshot(self, as_of: datetime) -> Snapshot:
        """Return the P-0D point-in-time view, never the eventual full truth."""

        return self.ledger.snapshot(as_of)

    def to_dict(self) -> dict[str, object]:
        """Materialize the corpus for an explicit caller-controlled export."""

        return {
            "manifest": dict(self.manifest),
            "events": [
                {
                    **event.manifest_record(),
                    "payload": thaw_json(event.payload),
                }
                for event in self.events
            ],
            "htl_registry": self.htl_registry.to_dict(),
            "hdc_episodes": [episode.to_dict() for episode in self.hdc_episodes],
            "hdb_benchmark": self.hdb_benchmark.to_dict(),
            "dos_records": [record.to_dict() for record in self.dos_records],
            "sas_releases": [release.to_dict() for release in self.sas_releases],
        }

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def export_json(self, destination: Path) -> None:
        """Write only when a caller explicitly requests an export destination."""

        destination.write_bytes(self.to_json_bytes())

    def events_for_episode(self, episode_id: str) -> tuple[CanonicalEvent, ...]:
        return tuple(
            event
            for event in self.events
            if isinstance(event.payload, Mapping)
            and event.payload.get("episode_id") == episode_id
        )

    def split_for_episode(self, episode_id: str) -> str:
        assignment = next(
            (item for item in self.assignments if item.episode_id == episode_id), None
        )
        if assignment is None:
            raise KeyError(episode_id)
        return assignment.split

    def latest_possible_availability(self) -> datetime:
        return max(event.available_at for event in self.events)

    def expected_event_count_without_corrections(self) -> int:
        streams = (
            self.config.organization_count
            * self.config.sites_per_organization
            * self.config.units_per_site
        )
        silent_start = max(
            12,
            min(self.config.episode_hours - 8, self.config.history_hours // 3),
        )
        silent_length = min(5, self.config.episode_hours - silent_start - 1)
        observed_hours = self.config.episode_hours - silent_length
        return streams * self.config.episodes_per_unit * observed_hours

    def temporal_span(self) -> timedelta:
        event_times = tuple(event.event_time for event in self.events)
        return max(event_times) - min(event_times)


def json_compatible(value: Mapping[str, Any]) -> dict[str, object]:
    """Detach a manifest after canonical validation."""

    canonical_json_bytes(value)
    return dict(value)
