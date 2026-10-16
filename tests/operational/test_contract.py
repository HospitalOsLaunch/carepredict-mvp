"""Independent contract examples: mixed granularity, time, versions and missingness."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from hospitalos.operational.contract import Cursor, Node, Observation, Topology, select_topology

T = dt.datetime(2025, 1, 1, tzinfo=dt.UTC)


def topology() -> Topology:
    return Topology(
        topology_id="site",
        valid_from=T,
        available_at=T,
        nodes=(
            Node(entity_id="H", level="hospital", capacity_beds=40.0),
            Node(entity_id="P", level="pole", parent_id="H", capacity_beds=40.0),
            Node(entity_id="A", level="unit", parent_id="P", capacity_beds=20.0),
            Node(entity_id="B", level="unit", parent_id="P", capacity_beds=20.0),
        ),
    )


def obs(**changes: Any) -> Observation:
    raw = {
        "event_id": "A:1",
        "entity_id": "A",
        "level": "unit",
        "source_system": "sih_fixture",
        "event_time": T,
        "available_at": T + dt.timedelta(hours=1),
        "values": {"occupancy": 3, "open_beds": 20},
    }
    return Observation.model_validate({**raw, **changes})


@pytest.mark.parametrize(
    "values",
    [
        {"occupancy": True},
        {"occupancy": 2.5},
        {"occupancy": -1},
        {"siips_score": float("nan")},
        {"nurse_count": float("inf")},
        {"ready_h": 12},
        {},
    ],
)
def test_unknown_latent_nonfinite_and_bad_counts_rejected(values: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        obs(values=values)


def test_explicit_missing_is_not_zero_and_proxy_is_not_siips() -> None:
    o = obs(values={"occupancy": None, "care_workload_proxy": 12.5})
    assert o.values["occupancy"] is None
    assert "siips_score" not in o.values


@pytest.mark.parametrize("clock", ["2025-01-01T00:00:00", "2024-12-31T23:00:00+00:00"])
def test_naive_and_reversed_clocks_fail(clock: str) -> None:
    with pytest.raises(ValueError):
        obs(available_at=clock)


def test_timezone_normalization_and_fall_back_are_instant_correct() -> None:
    a = obs(event_time="2026-10-25T02:00:00+02:00", available_at="2026-10-25T02:10:00+02:00")
    b = obs(event_time="2026-10-25T02:00:00+01:00", available_at="2026-10-25T02:10:00+01:00")
    assert b.event_time - a.event_time == dt.timedelta(hours=1)
    assert a.event_time.utcoffset() == dt.timedelta(0)


def test_topology_revision_is_not_used_before_availability() -> None:
    old = topology()
    new = Topology.model_validate(
        {**old.model_dump(), "version": 2, "available_at": T + dt.timedelta(hours=3)}
    )
    assert select_topology([old, new], T + dt.timedelta(hours=2)) == old
    assert select_topology([old, new], T + dt.timedelta(hours=3)) == new


@pytest.mark.parametrize("frontier", [("A",), ("P", "A"), ("A", "A"), ("UNKNOWN",)])
def test_incomplete_overlapping_or_unknown_frontier_rejected(frontier: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        topology().frontier(frontier)


def test_aggregate_observation_does_not_invent_children() -> None:
    cursor = Cursor()
    o = obs(entity_id="P", level="pole", event_id="P:1", values={"occupancy": 10})
    cursor.advance(T + dt.timedelta(hours=1), [o], topology())
    assert set(cursor.latest) == {"P"}
    assert topology().frontier(["P"])[0].level == "pole"


def test_future_receipt_and_changed_event_identity_fail() -> None:
    cursor = Cursor()
    with pytest.raises(ValueError, match="Future"):
        cursor.advance(T, [obs()], topology())
    cursor.advance(T + dt.timedelta(hours=1), [obs()], topology())
    with pytest.raises(ValueError, match="identity"):
        cursor.advance(T + dt.timedelta(hours=2), [obs(entity_id="B", version=2)], topology())


def test_revision_only_affects_new_origins_and_retry_cannot_refresh_age() -> None:
    cursor = Cursor()
    cursor.advance(T + dt.timedelta(hours=1), [obs()], topology())
    previous = cursor.latest["A"]
    revision = obs(version=2, values={"occupancy": 8}, available_at=T + dt.timedelta(hours=2))
    cursor.advance(T + dt.timedelta(hours=2), [revision], topology())
    assert previous.values["occupancy"] == 3
    assert cursor.latest["A"].values["occupancy"] == 8
    cursor.advance(
        T + dt.timedelta(hours=3), [obs(available_at=T + dt.timedelta(hours=3))], topology()
    )
    assert cursor.latest["A"] == revision


def test_same_instant_different_event_id_rejected() -> None:
    cursor = Cursor()
    with pytest.raises(ValueError, match="reconciliation"):
        cursor.advance(
            T + dt.timedelta(hours=1),
            [obs(), obs(event_id="other", event_time="2025-01-01T00:00:00.000Z")],
            topology(),
        )
