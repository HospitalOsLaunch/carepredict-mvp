"""Tests for split-before-windowing and isolation controls."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hfwm.evaluation.splits import (
    Episode,
    SplitAssignment,
    assign_temporal_splits,
    create_windows,
    split_manifest,
    validate_split_manifest,
)


def _episode(
    index: int,
    *,
    semantic: str | None = None,
    correction: str | None = None,
    site: str = "site-1",
) -> Episode:
    start = datetime(2020, 1, 1, tzinfo=UTC) + timedelta(hours=index * 1000)
    return Episode(
        episode_id=f"episode-{index:02d}",
        organization_id="org-1",
        site_id=site,
        unit_id="unit-1",
        start_at=start,
        end_at=start + timedelta(hours=500),
        semantic_hash=semantic or f"semantic-{index:02d}",
        correction_family=correction or f"correction-{index:02d}",
    )


def test_split_occurs_before_windowing_and_is_deterministic() -> None:
    """All windows inherit one already-frozen episode partition."""
    episodes = tuple(_episode(index) for index in range(20))
    first = assign_temporal_splits(episodes)
    second = assign_temporal_splits(reversed(episodes))
    assert first == second
    assert {assignment.split for assignment in first} == {"train", "validation", "test"}
    windows = create_windows(
        episodes,
        first,
        history=timedelta(hours=336),
        horizons=(timedelta(hours=6), timedelta(hours=24), timedelta(hours=72)),
        stride=timedelta(hours=24),
        purge_gap=timedelta(hours=168),
    )
    frozen = {assignment.episode_id: assignment.split for assignment in first}
    assert windows
    assert all(window.split == frozen[window.episode_id] for window in windows)


def test_corrections_and_exact_duplicates_are_indivisible() -> None:
    """Correction and semantic duplicate edges create one transitive group."""
    episodes = [_episode(index) for index in range(20)]
    episodes[10] = _episode(10, correction=episodes[9].correction_family)
    episodes[11] = _episode(11, semantic=episodes[10].semantic_hash)
    assignments = {item.episode_id: item for item in assign_temporal_splits(episodes)}
    group_ids = {assignments[f"episode-{index:02d}"].group_id for index in (9, 10, 11)}
    splits = {assignments[f"episode-{index:02d}"].split for index in (9, 10, 11)}
    assert len(group_ids) == 1
    assert len(splits) == 1


def test_whole_site_holdout_overrides_temporal_assignment() -> None:
    """Explicit unseen sites are assigned wholly to test."""
    episodes = tuple(_episode(index, site="held-out") for index in range(5))
    assignments = assign_temporal_splits(episodes, test_site_ids=frozenset({"held-out"}))
    assert {assignment.split for assignment in assignments} == {"test"}
    assert {assignment.reason for assignment in assignments} == {"site_holdout"}


def test_manifest_detects_cross_split_group() -> None:
    """A contamination group cannot be declared in two partitions."""
    assignments = (
        SplitAssignment("episode-1", "train", "group-x", "test"),
        SplitAssignment("episode-2", "test", "group-x", "test"),
    )
    manifest = split_manifest(assignments)
    assert validate_split_manifest(manifest) == ["contamination group spans splits: group-x"]


def test_window_creation_fails_when_purge_gap_is_violated() -> None:
    """Adjacent train and validation windows require the frozen purge gap."""
    episodes = (_episode(0), _episode(1))
    assignments = (
        SplitAssignment("episode-00", "train", "g0", "test"),
        SplitAssignment("episode-01", "validation", "g1", "test"),
    )
    with pytest.raises(ValueError, match="purge gap violated"):
        create_windows(
            episodes,
            assignments,
            history=timedelta(hours=336),
            horizons=(timedelta(hours=72),),
            stride=timedelta(hours=24),
            purge_gap=timedelta(hours=600),
        )
