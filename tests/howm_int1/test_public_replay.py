"""Regression cases for public replay of delayed transport and discharge events."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/filter_validation"))
from correction import LegacyPublicStream, W, assert_consistent
from hospitalos.howm.generator import refresh_private
from hospitalos.howm.world import Plan


def observation(kind, event_min, available_min=None, subject="old", **value):
    return event_min, event_min if available_min is None else available_min, kind, subject, "A", value


def replay(events, tick=6, route="home", stream=W.PublicStreamN):
    unit = dict(beds=[("bed", False)], roster={"IDE": [2] * 72, "AS": [2] * 72},
                minimum={"IDE": 1, "AS": 1})
    static = observation("static", 0, units={"A": unit}, c_tr=1, c_cl=1, aval_slots=0)
    placed = observation("placed", 0, bed="bed", unit="A", acuity=1, iso=False, transport=True)
    prefix = [static, placed]
    if route is not None:
        prefix.append(observation("route", 0, dest="B" if route == "transfer" else "", aval=route == "aval"))
    stream = stream(prefix + events)
    stream.advance(tick * 15 - 1)
    return stream, stream.to_engine_n(tick)


def test_home_finish_releases_dirty_at_event_time_once():
    finish = observation("transport_done", 60, 80)
    raw, eng = replay([finish, finish])
    stay, bed = eng.stays["old"], eng.beds["bed"]
    assert (stay.tr_end, stay.departed, bed.dirty_tick) == (4, 4, 4)
    assert (bed.state, bed.stay, eng.free_beds("A")) == ("dirty", None, [])
    assert (stay.tr_req, stay.tr_start) == (None, None)
    assert eng.tick == 6 and not eng.demand and not eng.tr_service
    assert "departure" not in raw.stays["old"] and raw.beds["bed"].data["state"] == "occ"
    assert_consistent(eng)
    assert raw.to_engine_n(6).beds == eng.beds


def test_invisible_finish_and_late_explicit_departure():
    events = [observation("transport_done", 60, 90), observation("departure", 60, 110, bed="bed")]
    _, before = replay(events, tick=6)
    raw, inferred = replay(events, tick=7)
    _, explicit = replay(events, tick=8)
    assert before.beds["bed"].state == "occ"
    assert "departure" not in raw.stays["old"]
    assert inferred.beds == explicit.beds and explicit.beds["bed"].dirty_tick == 4


def test_home_bed_returns_to_pool_only_after_cleaning(monkeypatch):
    _, eng = replay([observation("transport_done", 300)], tick=25)
    provider = W.ProvN(W.two_unit_structure("REPLAY_FIXTURE", 0), 1)
    monkeypatch.setattr(provider, "cleaning_end", lambda engine, bed: engine.tick + 1)
    monkeypatch.setattr(provider, "cleaning_capacity_drop", lambda engine, tick: 0)
    events = []
    eng.on_event = lambda _, kind, *rest: events.append(kind)
    eng.step(provider)
    assert eng.beds["bed"].state == "cleaning" and not eng.free_beds("A")
    eng.step(provider)
    assert [b.bed_id for b in eng.free_beds("A")] == ["bed"]
    assert events == ["cleaning_start", "cleaning_done"]


@pytest.mark.parametrize("partial", [{"aval": False}, {"dest": ""}, {"dest": "", "aval": None}])
def test_partial_route_waits_for_both_home_fields(partial):
    observations = [observation("route", 0, **partial), observation("transport_done", 60),
                    observation("route", 75, 90, dest="", aval=False)]
    _, unknown = replay(observations, tick=6, route=None)
    _, home = replay(observations, tick=7, route=None)
    assert unknown.beds["bed"].state == "occ"
    assert home.beds["bed"].state == "dirty" and home.beds["bed"].dirty_tick == 4


@pytest.mark.parametrize("kind,state", [("cleaning_start", "cleaning"), ("cleaning_done", "free"),
                                         ("placed", "occ")])
def test_old_finish_preserves_newer_bed_state(kind, state):
    update = (observation("placed", 75, 80, subject="new", bed="bed", unit="A", acuity=1,
                          iso=False, transport=False) if kind == "placed"
              else observation(kind, 75, 80, subject="bed"))
    _, eng = replay([update, observation("transport_done", 60, 84)])
    assert eng.beds["bed"].state == state
    assert eng.beds["bed"].stay == ("new" if kind == "placed" else None)
    assert "old" not in eng.stays
    assert_consistent(eng)


@pytest.mark.parametrize("route", ["transfer", "aval", None])
def test_finish_needs_confirmed_home_route_for_implicit_exit(route):
    _, eng = replay([observation("transport_done", 60, 75)], route=route)
    assert eng.beds["bed"].stay == "old" and eng.stays["old"].departed is None
    assert eng.aval_blocked == (["old"] if route == "aval" else [])
    assert not eng.tr_service


@pytest.mark.parametrize("start", [[], [observation("transport_start", 45, 80)]])
def test_downstream_wait_never_redraws_or_restarts_finished_service(start):
    _, eng = replay([observation("transport_done", 60, 70), *start], tick=44, route="aval")
    stay = eng.stays["old"]
    assert stay.tr_start == (3 if start else None)
    provider = W.ProvN(W.two_unit_structure("REPLAY_FIXTURE", 0), 1)
    events = []
    eng.on_event = lambda t, kind, sid, data: events.append((kind, sid))
    refresh_private(eng, provider)
    eng.apply_plan(Plan(coordinate=True), provider)
    eng.step(provider)  # tick 44 is an habitual transport request at 11:00
    assert stay.tr_end == 4 and stay.tr_req is None and stay.departed is None
    assert not any(k.startswith("transport") and sid == "old" for k, sid in events)
    assert eng.tr_service == [] and eng.beds["bed"].stay == "old"
    eng.spec_meta["aval_slots"] = 1
    while eng.tick <= 48:
        eng.step(provider)
    assert stay.departed == 48 and eng.aval_used[0] == 1


@pytest.mark.parametrize("has_start", [False, True])
def test_legacy_replays_historical_transport_prerequisites(has_start):
    events = [observation("transport_done", 60)]
    if has_start:
        events.append(observation("transport_start", 45, 82))
    _, old = replay(events, stream=LegacyPublicStream)
    s = old.stays["old"]
    assert old.beds["bed"].state == "occ" and not old.tr_service
    assert not s.authorised and not s.ready and not s.tr_accepted
    assert (s.tr_start, s.tr_end) == ((3, 4) if has_start else (None, None))
