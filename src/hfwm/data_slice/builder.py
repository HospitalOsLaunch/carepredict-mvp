"""Build the bounded HFWM-R0 hourly point-in-time dataset without training."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml

from hfwm.corpus import (
    SOURCE_ID,
    TemporalCorpus,
    build_contamination_records,
    build_temporal_corpus,
)
from hfwm.evaluation.decontamination import audit_contamination
from hfwm.evaluation.splits import Episode, split_manifest, validate_split_manifest
from p0d import CanonicalEvent, EventLedger, canonical_json_bytes, sha256_json, utc_text

DATA_SLICE_ID = "HFWM-R0-D0-SYNTHETIC-PIT"
DATASET_SCHEMA = "hfwm.r0.point-in-time-dataset.v1"
DATASET_MANIFEST_SCHEMA = "hfwm.r0.dataset-manifest.v1"
LEAKAGE_REPORT_SCHEMA = "hfwm.r0.temporal-leakage-report.v1"
TRANSFORMATION_VERSION = "hfwm-r0-point-in-time-data-slice.v1"
HORIZON_HOURS = 6
TARGETS = ("occupancy", "inflow")
REPRODUCTION_COMMAND = (
    "PYTHONPATH=src python scripts/hfwm/build_data_slice.py "
    "--output-dir artifacts/hfwm-r0/data-slice"
)


class DataSliceError(ValueError):
    """The bounded slice cannot be built without violating its frozen contract."""


@dataclass(frozen=True, slots=True)
class DataSliceBuild:
    """In-memory data and evidence, exported only by an explicit caller."""

    dataset: Mapping[str, object]
    dataset_manifest: Mapping[str, object]
    split_manifest: Mapping[str, object]
    temporal_leakage_report: Mapping[str, object]
    dataset_hash: str

    def export(self, output_dir: Path) -> tuple[Path, ...]:
        """Write the four required deterministic JSON artifacts."""

        output_dir.mkdir(parents=True, exist_ok=True)
        artifacts = (
            ("dataset.json", self.dataset),
            ("dataset_manifest.json", self.dataset_manifest),
            ("split_manifest.json", self.split_manifest),
            ("temporal_leakage_report.json", self.temporal_leakage_report),
        )
        paths: list[Path] = []
        for name, payload in artifacts:
            path = output_dir / name
            path.write_bytes(canonical_json_bytes(payload) + b"\n")
            paths.append(path)
        return tuple(paths)


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_rights_path() -> Path:
    return _repository_root() / "docs/research/hfwm/HFWM_R0_DATA_RIGHTS.yaml"


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _authorized_source(rights_path: Path) -> dict[str, object]:
    raw: Any = yaml.safe_load(rights_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise DataSliceError("data-rights registry must be an object")
    sources = raw.get("sources")
    if not isinstance(sources, list):
        raise DataSliceError("data-rights registry must contain sources")
    selected: Mapping[object, object] | None = None
    for source in sources:
        if isinstance(source, Mapping) and source.get("source_id") == SOURCE_ID:
            selected = source
            break
    if selected is None:
        raise DataSliceError(f"source absent from data-rights registry: {SOURCE_ID}")
    if selected.get("decision") != "allowed" or selected.get("evaluation_allowed") is not True:
        raise DataSliceError(f"source is not authorized for local evaluation: {SOURCE_ID}")
    required_strings = ("owner", "licence", "retention", "territory", "expiry")
    if any(not isinstance(selected.get(field), str) for field in required_strings):
        raise DataSliceError("authorized source rights metadata is incomplete")
    purposes = selected.get("allowed_purposes")
    if not isinstance(purposes, list) or not all(isinstance(item, str) for item in purposes):
        raise DataSliceError("authorized source purposes must be a list of strings")
    return {
        "source_id": SOURCE_ID,
        "source_kind": "first_party_deterministic_synthetic_fixture",
        "owner": selected["owner"],
        "licence": selected["licence"],
        "allowed_purposes": purposes,
        "retention": selected["retention"],
        "territory": selected["territory"],
        "expiry": selected["expiry"],
        "publication_allowed": selected.get("publication_allowed") is True,
        "weights_allowed": selected.get("weights_allowed") is True,
        "rights_registry": rights_path.relative_to(_repository_root()).as_posix(),
        "rights_registry_sha256": _file_sha256(rights_path),
    }


def _payload_int(event: CanonicalEvent, field: str) -> int:
    payload = event.payload
    if not isinstance(payload, Mapping):
        raise DataSliceError(f"event {event.event_id} payload must be an object")
    value = payload.get(field)
    if type(value) is not int:
        raise DataSliceError(f"event {event.event_id} has no integer {field}")
    return value


def _episode_id(event: CanonicalEvent) -> str:
    payload = event.payload
    if not isinstance(payload, Mapping):
        raise DataSliceError(f"event {event.event_id} payload must be an object")
    value = payload.get("episode_id")
    if not isinstance(value, str) or not value:
        raise DataSliceError(f"event {event.event_id} has no episode_id")
    return value


def _overlapping_episodes(episodes: tuple[Episode, ...]) -> list[dict[str, str]]:
    by_unit: dict[tuple[str, str, str], list[Episode]] = defaultdict(list)
    for episode in episodes:
        by_unit[(episode.organization_id, episode.site_id, episode.unit_id)].append(episode)
    overlaps: list[dict[str, str]] = []
    for unit, members in sorted(by_unit.items()):
        ordered = sorted(members, key=lambda item: (item.start_at, item.end_at, item.episode_id))
        for left, right in zip(ordered, ordered[1:], strict=False):
            if right.start_at <= left.end_at:
                overlaps.append(
                    {
                        "unit": "/".join(unit),
                        "left_episode_id": left.episode_id,
                        "right_episode_id": right.episode_id,
                    }
                )
    return overlaps


def _build_rows(
    corpus: TemporalCorpus,
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    events_by_episode: dict[str, list[CanonicalEvent]] = defaultdict(list)
    for event in corpus.events:
        events_by_episode[_episode_id(event)].append(event)
    ledgers = {
        episode_id: EventLedger(tuple(events))
        for episode_id, events in events_by_episode.items()
    }
    eventual_as_of = corpus.latest_possible_availability() + timedelta(hours=1)
    rows: list[dict[str, object]] = []
    violations: list[dict[str, str]] = []
    horizon = timedelta(hours=HORIZON_HOURS)

    for window in sorted(corpus.windows, key=lambda item: (item.episode_id, item.origin_at)):
        ledger = ledgers[window.episode_id]
        snapshot = ledger.snapshot(window.origin_at)
        history = snapshot.events
        if not history:
            raise DataSliceError(f"empty point-in-time history: {window.episode_id}")
        for event in history:
            if event.event_time > window.origin_at or event.available_at > window.origin_at:
                violations.append(
                    {"kind": "future_feature", "event_id": event.event_id}
                )
        latest = max(history, key=lambda event: event.replay_key())
        recent_start = window.origin_at - horizon
        recent = tuple(
            event
            for event in history
            if recent_start < event.event_time <= window.origin_at
        )
        target_end = window.origin_at + horizon
        future = tuple(
            event
            for event in ledger.replay(eventual_as_of)
            if window.origin_at < event.event_time <= target_end
        )
        for event in future:
            if not window.origin_at < event.event_time <= target_end:
                violations.append(
                    {"kind": "target_outside_horizon", "event_id": event.event_id}
                )
        target_end_events = tuple(event for event in future if event.event_time == target_end)
        if len(target_end_events) != 1 or len(future) != HORIZON_HOURS:
            raise DataSliceError(
                f"incomplete {HORIZON_HOURS}h target for {window.episode_id} at "
                f"{utc_text(window.origin_at)}"
            )
        assignment = next(
            item for item in corpus.assignments if item.episode_id == window.episode_id
        )
        if assignment.split != window.split:
            violations.append(
                {"kind": "window_split_mismatch", "episode_id": window.episode_id}
            )
        row_identity = {
            "episode_id": window.episode_id,
            "as_of": utc_text(window.origin_at),
            "horizon_hours": HORIZON_HOURS,
            "targets": list(TARGETS),
        }
        rows.append(
            {
                "example_id": sha256_json(row_identity),
                "split": window.split,
                "organization_id": window.organization_id,
                "site_id": window.site_id,
                "unit_id": window.unit_id,
                "episode_id": window.episode_id,
                "as_of": utc_text(window.origin_at),
                "history_start_at": utc_text(window.history_start_at),
                "target_end_at": utc_text(target_end),
                "feature_snapshot_id": snapshot.snapshot_id,
                "feature_event_count": len(history),
                "features": {
                    "occupancy": _payload_int(latest, "occupancy"),
                    "inflow_last_6h": sum(_payload_int(event, "inflow") for event in recent),
                    "observed_hours_last_6h": len(recent),
                },
                "targets": {
                    "occupancy": _payload_int(target_end_events[0], "occupancy"),
                    "inflow": sum(_payload_int(event, "inflow") for event in future),
                },
            }
        )
    return rows, violations


def build_point_in_time_data_slice(
    *,
    corpus: TemporalCorpus | None = None,
    rights_path: Path | None = None,
) -> DataSliceBuild:
    """Build the frozen 6-hour, two-target slice entirely in memory."""

    closed_corpus = corpus or build_temporal_corpus()
    if HORIZON_HOURS not in closed_corpus.config.horizons_hours:
        raise DataSliceError(f"corpus does not support the {HORIZON_HOURS}h horizon")
    closed_rights_path = (rights_path or _default_rights_path()).resolve(strict=True)
    source_manifest = _authorized_source(closed_rights_path)
    partition_manifest = split_manifest(closed_corpus.assignments)
    split_errors = validate_split_manifest(partition_manifest)
    contamination = audit_contamination(
        build_contamination_records(closed_corpus.episodes, closed_corpus.assignments)
    )
    overlaps = _overlapping_episodes(closed_corpus.episodes)
    rows, temporal_violations = _build_rows(closed_corpus)
    if split_errors or contamination or overlaps or temporal_violations:
        raise DataSliceError("temporal, overlap, split, or contamination audit failed")

    dataset_payload: dict[str, object] = {
        "schema_version": DATASET_SCHEMA,
        "slice_id": DATA_SLICE_ID,
        "grain": "hourly",
        "history_hours": closed_corpus.config.history_hours,
        "horizon_hours": HORIZON_HOURS,
        "targets": list(TARGETS),
        "rows": rows,
    }
    dataset_hash = sha256_json(dataset_payload)
    dataset = {**dataset_payload, "dataset_hash": dataset_hash}
    split_counts = Counter(str(row["split"]) for row in rows)
    event_times = tuple(event.event_time for event in closed_corpus.events)
    units = sorted({event.unit_id for event in closed_corpus.events})
    dataset_manifest: dict[str, object] = {
        "schema_version": DATASET_MANIFEST_SCHEMA,
        "slice_id": DATA_SLICE_ID,
        "dataset_hash": dataset_hash,
        "corpus_hash": closed_corpus.corpus_hash,
        "source": source_manifest,
        "period": {
            "event_time_start": utc_text(min(event_times)),
            "event_time_end": utc_text(max(event_times)),
        },
        "units": units,
        "event_contract": {
            "required_temporal_fields": [
                "event_time",
                "recorded_at",
                "available_at",
                "ingested_at",
            ],
            "snapshot_rule": "event_time <= as_of AND available_at <= as_of",
        },
        "grain": "hourly",
        "history_hours": closed_corpus.config.history_hours,
        "horizon_hours": HORIZON_HOURS,
        "targets": [
            {"name": "occupancy", "unit": "patients", "aggregation": "end_of_horizon"},
            {"name": "inflow", "unit": "patients/6h", "aggregation": "sum_over_horizon"},
        ],
        "transformations": [
            "hfwm-r0-temporal-corpus-v1",
            TRANSFORMATION_VERSION,
        ],
        "deduplication": "semantic_deduplicate plus cross-split contamination audit",
        "overlap_policy": "reject overlapping episodes within organization/site/unit",
        "split_before_windowing": True,
        "split_manifest_hash": partition_manifest["manifest_sha256"],
        "row_count": len(rows),
        "split_row_counts": dict(sorted(split_counts.items())),
        "reproduction_command": REPRODUCTION_COMMAND,
    }
    leakage_report: dict[str, object] = {
        "schema_version": LEAKAGE_REPORT_SCHEMA,
        "slice_id": DATA_SLICE_ID,
        "dataset_hash": dataset_hash,
        "status": "PASS",
        "as_of_rule": "feature.event_time <= as_of AND feature.available_at <= as_of",
        "target_rule": "as_of < target.event_time <= as_of + 6h",
        "split_before_windowing": True,
        "split_manifest_errors": split_errors,
        "cross_split_contamination_count": len(contamination),
        "overlapping_episode_count": len(overlaps),
        "temporal_violation_count": len(temporal_violations),
        "checked_row_count": len(rows),
    }
    return DataSliceBuild(
        dataset=dataset,
        dataset_manifest=dataset_manifest,
        split_manifest=partition_manifest,
        temporal_leakage_report=leakage_report,
        dataset_hash=dataset_hash,
    )
