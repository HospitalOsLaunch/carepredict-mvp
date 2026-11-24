from datetime import timedelta

import pytest

from hospitalos.hybrid.demo import demo_request
from hospitalos.hybrid.models import State
from hospitalos.hybrid.outlook import (
    Bookings,
    Emergency,
    Feed,
    Kind,
    Roster,
    UnitOutlook,
    check_feed,
    horizon_check,
)
from hospitalos.hybrid.synthetic_outlook import synthetic_outlook


def source_state() -> State:
    state = demo_request().state()
    unit = state.units[0].id
    return state.model_copy(update={"outlooks": (synthetic_outlook(state, unit),)})


def replace_feed(state: State, feed: Feed, append: bool = False) -> State:
    old = state.outlooks[0]
    feeds = tuple(f for f in old.feeds if append or f.kind != feed.kind)
    return state.model_copy(update={"outlooks": (UnitOutlook(id=old.id, feeds=(*feeds, feed)),)})


def test_source_coverage_and_fresh_empty_bookings() -> None:
    state = source_state()
    uid = state.units[0].id
    assert all(horizon_check(state, uid, d).data_ready for d in (3, 7))
    bare = state.model_copy(update={"outlooks": ()})
    assert [f.reasons for f in horizon_check(bare, uid, 3).feeds] == [("missing",)] * 4


@pytest.mark.parametrize(
    ("kind", "patch", "expected"),
    [
        ("bookings", {"status": "outage"}, "outage"),
        ("roster", {"validated": False}, "shift_or_skill_gap"),
        ("departures", {"records": ()}, "discharge_coverage"),
        ("emergency", {"records": ()}, "daily_coverage"),
        ("bookings", {"hospital_id": "another"}, "scope"),
    ],
)
def test_partial_sources_close_long_plan(
    kind: Kind, patch: dict[str, object], expected: str
) -> None:
    state = source_state()
    feed = next(f for f in state.outlooks[0].feeds if f.kind == kind)
    if kind == "departures" and not any(b.occupant for b in state.beds):
        from hospitalos.hybrid.models import Bed

        state = state.model_copy(
            update={
                "beds": (
                    *state.beds,
                    Bed(id="cohort", state="occupied", unit_id=state.units[0].id, occupant="stay"),
                )
            }
        )
    updated = replace_feed(state, feed.model_copy(update=patch))
    check = check_feed(updated, state.units[0].id, kind, state.at + timedelta(days=3))
    assert expected in check.reasons


def test_late_revisions_staleness_and_future_coverage_are_separate() -> None:
    state = source_state()
    unit = state.units[0].id
    feed = next(f for f in state.outlooks[0].feeds if isinstance(f, Bookings))
    end = state.at + timedelta(days=3)
    future = feed.model_copy(
        update={"revision": 2, "synced_at": state.at + timedelta(seconds=1), "status": "outage"}
    )
    history = replace_feed(state, future, True)
    assert check_feed(history, unit, "bookings", end).revision == 1
    assert (
        "outage"
        in check_feed(
            history.model_copy(update={"at": future.synced_at}), unit, "bookings", end
        ).reasons
    )
    old = state.at - timedelta(hours=2, seconds=1)
    assert (
        "stale"
        in check_feed(
            replace_feed(
                state, feed.model_copy(update=dict(issued_at=old, available_at=old, synced_at=old))
            ),
            unit,
            "bookings",
            end,
        ).reasons
    )
    short = replace_feed(state, feed.model_copy(update={"covers_until": end}))
    assert horizon_check(short, unit, 3).data_ready
    assert not horizon_check(short, unit, 7).data_ready


def test_double_booked_people_and_incomplete_civil_days() -> None:
    state = source_state()
    roster = next(f for f in state.outlooks[0].feeds if isinstance(f, Roster))
    broken = replace_feed(
        state, roster.model_copy(update={"shifts": (*roster.shifts, roster.shifts[0])})
    )
    assert not horizon_check(broken, roster.unit_id, 3).data_ready
    ed = next(f for f in state.outlooks[0].feeds if isinstance(f, Emergency))
    assert len(ed.records) == 8  # mid-day handover intersects eight civil dates in seven days
    assert not horizon_check(
        replace_feed(state, ed.model_copy(update={"records": ed.records[:-1]})), roster.unit_id, 7
    ).data_ready
