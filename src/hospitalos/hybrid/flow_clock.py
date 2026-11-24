"""Synthetic residence-time prior for the four versioned unit-flow generators."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .innovations import uniform
from .models import State
from .outlook import KINDS, Departures, Emergency, check_feed, latest

VERSION = "synthetic-residence-v2"
UNITS = {
    "medecine-polyvalente": 0,
    "court-sejour-geriatrique": 1,
    "medecine-interne": 0,
    "pneumologie": 0,
}
ZONE = ZoneInfo("Europe/Paris")


def declared(state: State) -> Departures | None:
    if len(state.units) == 1:
        feed, _ = latest(state, state.units[0].id, "departures")
        if isinstance(feed, Departures) and feed.cohort_profile == VERSION:
            return feed
    return None


def available(state: State, horizon: int) -> bool:
    feed = declared(state)
    if feed is None or state.issues or feed.unit_id not in UNITS:
        return False
    unit = feed.unit_id
    end = state.at + timedelta(minutes=horizon)
    ed, _ = latest(state, unit, "emergency")
    return (
        isinstance(ed, Emergency)
        and ed.allocation_rule == "direct-to-beneficiary-v1"
        and all(
            f is not None
            and f.provenance == "synthetic"
            and not check_feed(state, unit, k, end).reasons
            for k in KINDS
            for f, _ in [latest(state, unit, k)]
        )
    )


@dataclass(frozen=True)
class CohortClock:
    origin: datetime
    hospital: str
    unit: str
    seed: int
    scenario: int
    # Only publicly timed and logistically uncomplicated residents enter this cohort.
    residents: tuple[tuple[str, datetime], ...]

    @classmethod
    def from_feed(cls, state: State, feed: Departures, seed: int, scenario: int) -> CohortClock:
        allowed = {
            d.id
            for d in state.discharges
            if d.documents_ready is True
            and d.transport_required is False
            and d.downstream_required is False
            and d.escort_required is False
        }
        occupied = {b.occupant for b in state.beds if b.unit_id == feed.unit_id}
        residents = tuple(
            (r.stay_id, r.admitted_at)
            for r in feed.records
            if r.stay_id in occupied and r.stay_id in allowed and r.admitted_at is not None
        )
        return cls(state.at, state.hospital_id, feed.unit_id, seed, scenario, residents)

    def validate(self, state: State, horizon: int) -> None:
        feed = declared(state)
        if (
            feed is None
            or not available(state, horizon)
            or self != CohortClock.from_feed(state, feed, self.seed, self.scenario)
        ):
            raise ValueError("Unverified cohort clock for this unit, origin or source coverage")

    def departure(self, patient: str, admission: datetime) -> int | None:
        """Sample local discharge day/time conditional on survival at the last known instant."""
        after = max(admission, self.origin)
        day = admission.astimezone(ZONE).date()
        intervals = []
        for length in (1, 2, 2, 3, 4, 5):
            start = datetime.combine(
                day + timedelta(days=length + UNITS[self.unit]), time(7), ZONE
            ).astimezone(self.origin.tzinfo)
            first = max(0, math.floor((after - start).total_seconds() / 60) + 1)
            if first < 60:
                intervals.append((start, first))
        count = sum(60 - first for _, first in intervals)
        if not count:
            return None
        rank = int(
            count
            * uniform(
                self.seed,
                self.scenario,
                "synthetic-stay-v2",
                f"{self.hospital}:{self.unit}:{patient}",
            )
        )
        for start, first in intervals:
            if rank < 60 - first:
                return math.ceil(((start - self.origin).total_seconds() / 60) + first + rank)
            rank -= 60 - first
        raise AssertionError("Invalid conditional stay quantile")
