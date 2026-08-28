"""Deterministic point-in-time dataset construction for P-0D."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from .canonical import CanonicalEvent, canonical_json_bytes, utc_text
from .ledger import Snapshot, semantic_deduplicate

SplitName = Literal["train", "validation", "test"]
HoldoutLevel = Literal["organization", "site", "unit", "episode"]


class DatasetBuildError(ValueError):
    """The requested dataset would not have a closed reproducible identity."""


@dataclass(frozen=True, slots=True, order=True)
class HierarchyPath:
    organization_id: str
    site_id: str
    unit_id: str
    episode_id: str

    @classmethod
    def from_event(cls, event: CanonicalEvent) -> HierarchyPath:
        payload = event.payload
        if not isinstance(payload, Mapping):
            raise DatasetBuildError("dataset events require object payloads")
        organization_id = payload.get("organization_id")
        episode_id = payload.get("episode_id")
        if not isinstance(organization_id, str) or not organization_id:
            raise DatasetBuildError("payload.organization_id is required")
        if not isinstance(episode_id, str) or not episode_id:
            raise DatasetBuildError("payload.episode_id is required")
        return cls(organization_id, event.site_id, event.unit_id, episode_id)

    def group(self, level: HoldoutLevel) -> tuple[str, ...]:
        fields = (
            self.organization_id,
            self.site_id,
            self.unit_id,
            self.episode_id,
        )
        size = {"organization": 1, "site": 2, "unit": 3, "episode": 4}[level]
        return fields[:size]

    def as_dict(self) -> dict[str, str]:
        return {
            "organization_id": self.organization_id,
            "site_id": self.site_id,
            "unit_id": self.unit_id,
            "episode_id": self.episode_id,
        }


@dataclass(frozen=True, slots=True)
class SplitConfig:
    """Integer-basis-point split policy, independent from platform floats."""

    train_bp: int = 7_000
    validation_bp: int = 1_500
    test_bp: int = 1_500
    seed: str = "hospitalos-p0d-v1"
    holdout_level: HoldoutLevel = "episode"

    def __post_init__(self) -> None:
        fractions = (self.train_bp, self.validation_bp, self.test_bp)
        if (
            any(type(value) is not int or value < 0 for value in fractions)
            or sum(fractions) != 10_000
            or not self.seed
            or self.holdout_level not in {"organization", "site", "unit", "episode"}
        ):
            raise DatasetBuildError("split configuration is not closed")

    def assign(self, hierarchy: HierarchyPath) -> SplitName:
        group = hierarchy.group(self.holdout_level)
        digest = hashlib.sha256(
            self.seed.encode("utf-8") + b"\0" + canonical_json_bytes(list(group))
        ).digest()
        bucket = int.from_bytes(digest[:8], "big") % 10_000
        if bucket < self.train_bp:
            return "train"
        if bucket < self.train_bp + self.validation_bp:
            return "validation"
        return "test"

    def manifest(self) -> dict[str, object]:
        return {
            "train_bp": self.train_bp,
            "validation_bp": self.validation_bp,
            "test_bp": self.test_bp,
            "seed": self.seed,
            "holdout_level": self.holdout_level,
            "hierarchy_order": [
                "organization_id",
                "site_id",
                "unit_id",
                "episode_id",
                "event_time",
            ],
        }


@dataclass(frozen=True, slots=True)
class AssignedEvent:
    split: SplitName
    hierarchy: HierarchyPath
    event: CanonicalEvent


@dataclass(frozen=True, slots=True)
class DatasetWindow:
    split: SplitName
    hierarchy: HierarchyPath
    event_ids: tuple[str, ...]
    start_time: str
    end_time: str

    def manifest(self) -> dict[str, object]:
        return {
            "split": self.split,
            "hierarchy": self.hierarchy.as_dict(),
            "event_ids": list(self.event_ids),
            "start_time": self.start_time,
            "end_time": self.end_time,
        }


@dataclass(frozen=True, slots=True)
class DatasetBuild:
    snapshot_id: str
    assigned_events: tuple[AssignedEvent, ...]
    windows: tuple[DatasetWindow, ...]
    manifest: Mapping[str, object]
    dataset_id: str


def assign_splits(
    events: tuple[CanonicalEvent, ...], config: SplitConfig
) -> tuple[AssignedEvent, ...]:
    """Assign immutable observations before any rolling window can be formed."""

    deduplicated = semantic_deduplicate(events)
    ordered = sorted(
        deduplicated,
        key=lambda event: (
            HierarchyPath.from_event(event),
            event.event_time,
            event.replay_key(),
        ),
    )
    return tuple(
        AssignedEvent(
            split=config.assign(HierarchyPath.from_event(event)),
            hierarchy=HierarchyPath.from_event(event),
            event=event,
        )
        for event in ordered
    )


def window_assigned_events(
    assigned: tuple[AssignedEvent, ...], *, window_size: int, stride: int
) -> tuple[DatasetWindow, ...]:
    if type(window_size) is not int or window_size < 1:
        raise DatasetBuildError("window_size must be a positive integer")
    if type(stride) is not int or stride < 1:
        raise DatasetBuildError("stride must be a positive integer")
    grouped: dict[tuple[SplitName, HierarchyPath], list[CanonicalEvent]] = {}
    for item in assigned:
        grouped.setdefault((item.split, item.hierarchy), []).append(item.event)
    windows: list[DatasetWindow] = []
    for (split, hierarchy), events in sorted(grouped.items()):
        ordered = sorted(events, key=lambda event: event.replay_key())
        for start in range(0, len(ordered) - window_size + 1, stride):
            members = ordered[start : start + window_size]
            windows.append(
                DatasetWindow(
                    split=split,
                    hierarchy=hierarchy,
                    event_ids=tuple(event.event_id for event in members),
                    start_time=utc_text(members[0].event_time),
                    end_time=utc_text(members[-1].event_time),
                )
            )
    return tuple(windows)


def build_dataset(
    snapshot: Snapshot,
    *,
    split_config: SplitConfig | None = None,
    window_size: int,
    stride: int = 1,
) -> DatasetBuild:
    if split_config is None:
        split_config = SplitConfig()
    assigned = assign_splits(snapshot.events, split_config)
    windows = window_assigned_events(assigned, window_size=window_size, stride=stride)
    assignments: dict[tuple[str, ...], SplitName] = {}
    for item in assigned:
        group = item.hierarchy.group(split_config.holdout_level)
        previous = assignments.setdefault(group, item.split)
        if previous != item.split:
            raise DatasetBuildError("one hierarchical group crossed split boundaries")
    manifest: dict[str, object] = {
        "schema": "hospitalos.p0d.dataset-manifest/1",
        "snapshot_id": snapshot.snapshot_id,
        "split_policy": split_config.manifest(),
        "split_assignments": [
            {"group": list(group), "split": split} for group, split in sorted(assignments.items())
        ],
        "events": [
            {
                "event_id": item.event.event_id,
                "payload_hash": item.event.payload_hash,
                "split": item.split,
                "hierarchy": item.hierarchy.as_dict(),
                "event_time": utc_text(item.event.event_time),
                "available_at": utc_text(item.event.available_at),
            }
            for item in assigned
        ],
        "window_size": window_size,
        "stride": stride,
        "windows": [window.manifest() for window in windows],
    }
    dataset_id = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    manifest = {**manifest, "dataset_id": dataset_id}
    return DatasetBuild(
        snapshot_id=snapshot.snapshot_id,
        assigned_events=assigned,
        windows=windows,
        manifest=manifest,
        dataset_id=dataset_id,
    )
