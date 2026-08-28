"""Split-before-windowing primitives for point-in-time hospital episodes."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from hfwm.evaluation.canonical import semantic_hash

SplitName = Literal["train", "validation", "test"]
_SPLIT_ORDER: dict[SplitName, int] = {"train": 0, "validation": 1, "test": 2}


@dataclass(frozen=True)
class Episode:
    """An indivisible episode used to decide partitions before windowing."""

    episode_id: str
    organization_id: str
    site_id: str
    unit_id: str
    start_at: datetime
    end_at: datetime
    semantic_hash: str
    correction_family: str

    def __post_init__(self) -> None:
        if not self.episode_id:
            raise ValueError("episode_id must not be empty")
        if not self.semantic_hash or not self.correction_family:
            raise ValueError("semantic_hash and correction_family must not be empty")
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise ValueError("episode timestamps must be timezone-aware")
        if self.end_at < self.start_at:
            raise ValueError("episode end_at precedes start_at")


@dataclass(frozen=True)
class SplitAssignment:
    """Frozen assignment of one episode to one split."""

    episode_id: str
    split: SplitName
    group_id: str
    reason: str


@dataclass(frozen=True)
class EvaluationWindow:
    """A window emitted only after the episode assignment is frozen."""

    episode_id: str
    organization_id: str
    site_id: str
    unit_id: str
    split: SplitName
    origin_at: datetime
    history_start_at: datetime
    target_end_at: datetime


def assign_temporal_splits(
    episodes: Iterable[Episode],
    *,
    train_fraction: float = 0.70,
    validation_fraction: float = 0.15,
    test_site_ids: frozenset[str] = frozenset(),
    test_organization_ids: frozenset[str] = frozenset(),
) -> tuple[SplitAssignment, ...]:
    """Assign contamination groups before creating any forecast window.

    Temporal boundaries are computed independently per unit on groups ordered by
    their latest episode end. Corrections and exact semantic duplicates form one
    indivisible group. Explicit organization/site holdouts override temporal splits.
    """
    if not 0.0 < train_fraction < 1.0:
        raise ValueError("train_fraction must be in (0, 1)")
    if not 0.0 < validation_fraction < 1.0 - train_fraction:
        raise ValueError("validation_fraction must leave a non-empty test fraction")
    materialized = tuple(episodes)
    by_id = {episode.episode_id: episode for episode in materialized}
    if len(by_id) != len(materialized):
        raise ValueError("duplicate episode_id")

    parents = {episode.episode_id: episode.episode_id for episode in materialized}

    def find(episode_id: str) -> str:
        while parents[episode_id] != episode_id:
            parents[episode_id] = parents[parents[episode_id]]
            episode_id = parents[episode_id]
        return episode_id

    def union(left_id: str, right_id: str) -> None:
        left_root = find(left_id)
        right_root = find(right_id)
        if left_root != right_root:
            first, second = sorted((left_root, right_root))
            parents[second] = first

    by_correction: dict[str, str] = {}
    by_semantic_hash: dict[str, str] = {}
    for episode in sorted(materialized, key=lambda item: item.episode_id):
        correction_peer = by_correction.setdefault(episode.correction_family, episode.episode_id)
        semantic_peer = by_semantic_hash.setdefault(episode.semantic_hash, episode.episode_id)
        union(episode.episode_id, correction_peer)
        union(episode.episode_id, semantic_peer)

    components: dict[str, list[Episode]] = defaultdict(list)
    for episode in materialized:
        components[find(episode.episode_id)].append(episode)
    group_members: dict[str, list[Episode]] = {}
    for members in components.values():
        group_id = semantic_hash(
            {
                "episode_ids": sorted(member.episode_id for member in members),
                "correction_families": sorted({member.correction_family for member in members}),
                "semantic_hashes": sorted({member.semantic_hash for member in members}),
            }
        )
        group_members[group_id] = members

    by_unit: dict[tuple[str, str, str], list[tuple[str, list[Episode]]]] = defaultdict(list)
    assignments: dict[str, SplitAssignment] = {}
    for group_id, members in sorted(group_members.items()):
        holdout_reasons: set[str] = set()
        if any(member.organization_id in test_organization_ids for member in members):
            holdout_reasons.add("organization_holdout")
        if any(member.site_id in test_site_ids for member in members):
            holdout_reasons.add("site_holdout")
        if holdout_reasons:
            for member in members:
                assignments[member.episode_id] = SplitAssignment(
                    episode_id=member.episode_id,
                    split="test",
                    group_id=group_id,
                    reason="+".join(sorted(holdout_reasons)),
                )
            continue
        unit_keys = {
            (member.organization_id, member.site_id, member.unit_id) for member in members
        }
        if len(unit_keys) != 1:
            raise ValueError(
                "a correction/duplicate group spans units without an explicit holdout"
            )
        by_unit[next(iter(unit_keys))].append((group_id, members))

    for unit_key, groups in sorted(by_unit.items()):
        del unit_key
        ordered = sorted(
            groups,
            key=lambda item: (
                max(member.end_at for member in item[1]),
                min(member.start_at for member in item[1]),
                item[0],
            ),
        )
        count = len(ordered)
        train_stop = max(1, int(count * train_fraction)) if count else 0
        validation_stop = max(train_stop + 1, int(count * (train_fraction + validation_fraction)))
        validation_stop = min(validation_stop, count)
        for index, (group_id, members) in enumerate(ordered):
            split: SplitName
            if index < train_stop:
                split = "train"
            elif index < validation_stop:
                split = "validation"
            else:
                split = "test"
            for member in members:
                assignments[member.episode_id] = SplitAssignment(
                    episode_id=member.episode_id,
                    split=split,
                    group_id=group_id,
                    reason="temporal_order_within_unit",
                )
    return tuple(assignments[key] for key in sorted(assignments))


def create_windows(
    episodes: Iterable[Episode],
    assignments: Iterable[SplitAssignment],
    *,
    history: timedelta,
    horizons: tuple[timedelta, ...],
    stride: timedelta,
    purge_gap: timedelta,
) -> tuple[EvaluationWindow, ...]:
    """Create windows after assignments and reject windows crossing episode bounds."""
    if history <= timedelta(0) or stride <= timedelta(0):
        raise ValueError("history and stride must be positive")
    if purge_gap < timedelta(0):
        raise ValueError("purge_gap must not be negative")
    if not horizons or any(horizon <= timedelta(0) for horizon in horizons):
        raise ValueError("horizons must contain positive durations")
    by_assignment = {assignment.episode_id: assignment for assignment in assignments}
    windows: list[EvaluationWindow] = []
    maximum_horizon = max(horizons)
    for episode in sorted(episodes, key=lambda item: item.episode_id):
        assignment = by_assignment.get(episode.episode_id)
        if assignment is None:
            raise ValueError(f"episode has no frozen split assignment: {episode.episode_id}")
        first_origin = episode.start_at + history
        last_origin = episode.end_at - maximum_horizon
        origin = first_origin
        while origin <= last_origin:
            windows.append(
                EvaluationWindow(
                    episode_id=episode.episode_id,
                    organization_id=episode.organization_id,
                    site_id=episode.site_id,
                    unit_id=episode.unit_id,
                    split=assignment.split,
                    origin_at=origin,
                    history_start_at=origin - history,
                    target_end_at=origin + maximum_horizon,
                )
            )
            origin += stride
    _validate_temporal_purge(windows, purge_gap=purge_gap)
    return tuple(windows)


def _validate_temporal_purge(
    windows: Iterable[EvaluationWindow], *, purge_gap: timedelta
) -> None:
    """Reject cross-split windows whose target/history spans are too close."""
    materialized = tuple(windows)
    by_episode: dict[str, set[SplitName]] = defaultdict(set)
    for window in materialized:
        by_episode[window.episode_id].add(window.split)
    leaked = sorted(episode_id for episode_id, splits in by_episode.items() if len(splits) > 1)
    if leaked:
        raise ValueError(f"episodes span partitions: {leaked}")
    if purge_gap == timedelta(0):
        return
    by_scope_and_split: dict[
        tuple[str, str, str], dict[SplitName, list[EvaluationWindow]]
    ] = defaultdict(lambda: defaultdict(list))
    for window in materialized:
        scope = (window.organization_id, window.site_id, window.unit_id)
        by_scope_and_split[scope][window.split].append(window)
    ordered_splits: tuple[SplitName, ...] = ("train", "validation", "test")
    for scope, by_split in by_scope_and_split.items():
        for left, right in zip(ordered_splits, ordered_splits[1:], strict=False):
            if not by_split[left] or not by_split[right]:
                continue
            latest_left = max(window.target_end_at for window in by_split[left])
            earliest_right = min(window.history_start_at for window in by_split[right])
            if earliest_right - latest_left < purge_gap:
                raise ValueError(
                    f"purge gap violated between {left} and {right} for scope {scope}"
                )


def split_manifest(assignments: Iterable[SplitAssignment]) -> dict[str, Any]:
    """Return a stable, content-addressed split manifest."""
    rows = [
        {
            "episode_id": assignment.episode_id,
            "split": assignment.split,
            "group_id": assignment.group_id,
            "reason": assignment.reason,
        }
        for assignment in sorted(assignments, key=lambda item: item.episode_id)
    ]
    payload = {"schema_version": "hfwm.split-manifest.v1", "assignments": rows}
    return {**payload, "manifest_sha256": semantic_hash(payload)}


def validate_split_manifest(manifest: Mapping[str, Any]) -> list[str]:
    """Validate identity uniqueness and group isolation in a split manifest."""
    errors: set[str] = set()
    assignments = manifest.get("assignments")
    if not isinstance(assignments, list):
        return ["assignments must be a list"]
    episode_splits: dict[str, set[str]] = defaultdict(set)
    group_splits: dict[str, set[str]] = defaultdict(set)
    for row in assignments:
        if not isinstance(row, dict):
            errors.add("assignment must be an object")
            continue
        episode_id = row.get("episode_id")
        group_id = row.get("group_id")
        split = row.get("split")
        if not isinstance(episode_id, str) or not isinstance(group_id, str):
            errors.add("assignment identity fields must be strings")
            continue
        if split not in _SPLIT_ORDER:
            errors.add(f"invalid split for {episode_id}: {split}")
            continue
        episode_splits[episode_id].add(split)
        group_splits[group_id].add(split)
    errors.update(
        f"episode spans splits: {episode_id}"
        for episode_id, splits in episode_splits.items()
        if len(splits) > 1
    )
    errors.update(
        f"contamination group spans splits: {group_id}"
        for group_id, splits in group_splits.items()
        if len(splits) > 1
    )
    payload = {
        "schema_version": manifest.get("schema_version"),
        "assignments": assignments,
    }
    if manifest.get("manifest_sha256") != semantic_hash(payload):
        errors.add("manifest_sha256 mismatch")
    return sorted(errors)
