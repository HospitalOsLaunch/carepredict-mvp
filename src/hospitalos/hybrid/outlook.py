"""Four as-of feeds for a unit's multi-day plan. A successful empty export declares coverage."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from statistics import mean
from typing import TYPE_CHECKING, Annotated, Any, Literal, Self
from zoneinfo import ZoneInfo

from pydantic import (
    Field,
    SerializerFunctionWrapHandler,
    StrictInt,
    field_validator,
    model_serializer,
    model_validator,
)

from hospitalos.decision_support.contracts import Skill, StaffShift
from hospitalos.operational.contract import Closed, Identifier, instant

from .unit_schedule import Booking, StaffOffer

if TYPE_CHECKING:
    from .models import State

Count = Annotated[StrictInt, Field(ge=0)]
Kind = Literal["bookings", "departures", "roster", "emergency"]
KINDS: tuple[Kind, ...] = ("bookings", "departures", "roster", "emergency")


class Receipt(Closed):
    schema_version: Literal["UNIT_OUTLOOK_1"] = "UNIT_OUTLOOK_1"
    hospital_id: Identifier
    unit_id: Identifier
    source: Identifier
    provenance: Literal["synthetic", "hospital_export"] = "hospital_export"
    revision: Annotated[StrictInt, Field(gt=0)]
    timezone: Literal["Europe/Paris"] = "Europe/Paris"
    issued_at: datetime
    available_at: datetime
    synced_at: datetime
    covers_from: datetime
    covers_until: datetime
    status: Literal["complete", "outage", "partial"]

    @field_validator("issued_at", "available_at", "synced_at", "covers_from", "covers_until")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return instant(value)

    @model_validator(mode="after")
    def clocks(self) -> Self:
        if (
            not self.issued_at <= self.available_at <= self.synced_at
            or self.covers_until <= self.covers_from
        ):
            raise ValueError("Invalid source clocks or coverage")
        return self


class Bookings(Receipt):
    kind: Literal["bookings"] = "bookings"
    records: tuple[Booking, ...]


class DepartureEstimate(Closed):
    stay_id: Identifier
    estimate: datetime | None
    reviewed_at: datetime
    admitted_at: datetime | None = None

    @model_serializer(mode="wrap")
    def write_public(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        fields: dict[str, Any] = handler(self)
        if self.admitted_at is None:
            fields.pop("admitted_at", None)
        return fields

    @field_validator("estimate", "reviewed_at", "admitted_at")
    @classmethod
    def clock(cls, value: datetime | None) -> datetime | None:
        return instant(value) if value else None


class Departures(Receipt):
    kind: Literal["departures"] = "departures"
    records: tuple[DepartureEstimate, ...]
    cohort_profile: Literal["synthetic-residence-v2"] | None = None

    @model_serializer(mode="wrap")
    def write_public(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        fields: dict[str, Any] = handler(self)
        if self.cohort_profile is None:
            fields.pop("cohort_profile", None)
        return fields


class StaffCapacity(Closed):
    start: datetime
    end: datetime
    staffed_beds: Count
    required: dict[Skill, Count]

    @field_validator("start", "end")
    @classmethod
    def clock(cls, value: datetime) -> datetime:
        return instant(value)

    @model_validator(mode="after")
    def interval(self) -> Self:
        if self.end <= self.start or set(self.required) != {"IDE", "AS"}:
            raise ValueError("Declare both skill minima and a positive shift")
        if self.staffed_beds and not sum(self.required.values()):
            raise ValueError("Staffed places require a validated skill allocation")
        return self


class ExternalShift(StaffShift):
    unit_id: Identifier


class Roster(Receipt):
    kind: Literal["roster"] = "roster"
    validated: bool
    shifts: tuple[StaffShift, ...]
    external_shifts: tuple[ExternalShift, ...] | None = None
    capacity: tuple[StaffCapacity, ...]


class DayDemand(Closed):
    day: date
    # Equally weighted, non-negative draws for ED patients directed to the beneficiary.
    counts: Annotated[
        tuple[Annotated[StrictInt, Field(ge=0, le=200)], ...], Field(min_length=1, max_length=128)
    ]


class Emergency(Receipt):
    kind: Literal["emergency"] = "emergency"
    allocation_rule: Identifier
    records: tuple[DayDemand, ...]


Feed = Annotated[Bookings | Departures | Roster | Emergency, Field(discriminator="kind")]


class UnitOutlook(Closed):
    kind: Literal["unit_outlook"] = "unit_outlook"
    id: Identifier  # beneficiary
    feeds: Annotated[tuple[Feed, ...], Field(max_length=64)]


class FeedCheck(Closed):
    kind: Kind
    source: str | None = None
    revision: int | None = None
    issued_at: datetime | None = None
    received_at: datetime | None = None
    synced_at: datetime | None = None
    covers_until: datetime | None = None
    covered: int | None = None
    expected: int | None = None
    reasons: tuple[str, ...]


class PublicDay(Closed):
    day: date
    bookings: int | None
    estimated_departures: int | None
    min_staffed_beds: int | None
    expected_ed_full_day: float | None


class HorizonCheck(Closed):
    perspective: tuple[PublicDay, ...] = ()
    days: int
    feeds: tuple[FeedCheck, ...]
    data_ready: bool
    qualified: bool = False
    reasons: tuple[str, ...] = ()


def civil_days(start: datetime, end: datetime, zone: str) -> tuple[date, ...]:
    tz = ZoneInfo(zone)
    first, last = (
        start.astimezone(tz).date(),
        (end - timedelta(microseconds=1)).astimezone(tz).date(),
    )
    return tuple(first + timedelta(days=i) for i in range((last - first).days + 1))


def latest(state: State, unit: str, kind: Kind) -> tuple[Feed | None, tuple[str, ...]]:
    rows = [
        f
        for o in state.outlooks
        if o.id == unit
        for f in o.feeds
        if f.kind == kind and f.synced_at <= state.at
    ]
    if not rows:
        return None, ("missing",)
    if any(f.unit_id != unit or f.hospital_id != state.hospital_id for f in rows):
        return None, ("scope",)
    if len({f.source for f in rows}) != 1:
        return None, ("conflict",)
    rev = max(f.revision for f in rows)
    same_revision = [f for f in rows if f.revision == rev]
    if len({f.model_dump_json(exclude={"synced_at"}) for f in same_revision}) != 1:
        return None, ("conflict",)
    latest_sync = max(f.synced_at for f in rows if f.revision == rev)
    matches = [f for f in rows if f.revision == rev and f.synced_at == latest_sync]
    if len({f.model_dump_json() for f in matches}) != 1:
        return None, ("conflict",)
    return matches[0], ()


def roster_valid(feed: Roster, start: datetime, end: datetime) -> bool:
    if (
        not feed.validated
        or feed.external_shifts is None
        or any(s.end <= s.start for s in (*feed.shifts, *feed.external_shifts))
    ):
        return False
    shifts = [s for s in feed.shifts if s.start < end and start < s.end]
    outside = [x for x in feed.external_shifts if x.start < end and start < x.end]
    if any(x.unit_id == feed.unit_id for x in outside):
        return False
    for i, s in enumerate(shifts):
        if s.status != "confirmed" or any(
            t.staff_id == s.staff_id and s.start < t.end and t.start < s.end
            for t in (*shifts[:i], *outside)
        ):
            return False
    intervals: tuple[StaffShift | StaffCapacity, ...] = (*shifts, *feed.capacity)
    boundaries = sorted(
        {start, end} | {v for x in intervals for v in (x.start, x.end) if start < v < end}
    )
    for cut in boundaries[:-1]:
        bands = [b for b in feed.capacity if b.start <= cut < b.end]
        if len(bands) != 1:
            return False
        for role, minimum in bands[0].required.items():
            if sum(s.skill == role and s.start <= cut < s.end for s in shifts) < minimum:
                return False
    return True


def check_feed(state: State, unit: str, kind: Kind, end: datetime) -> FeedCheck:
    feed, reasons = latest(state, unit, kind)
    if feed is None:
        return FeedCheck(kind=kind, reasons=reasons)
    at = state.at
    problems: list[str] = []
    if feed.status != "complete":
        problems.append(feed.status)
    age = at - (feed.issued_at if isinstance(feed, Emergency) else feed.synced_at)
    if age > timedelta(hours=2 if isinstance(feed, Bookings) else 24):
        problems.append("stale")
    if (
        feed.covers_from > at
        or (not isinstance(feed, Departures) and feed.covers_until < end)
        or feed.covers_until <= at
    ):
        problems.append("coverage")
    covered = expected = None
    if isinstance(feed, Bookings):
        ids = [b.request.request_id for b in feed.records]
        if len(ids) != len(set(ids)):
            problems.append("duplicate_booking")
        for b in feed.records:
            provenance = b.request.provenance
            if (
                instant(provenance.event_time) > instant(provenance.available_at)
                or instant(provenance.available_at) > feed.available_at
            ):
                problems.append("future_record")
                break
    elif isinstance(feed, Departures):
        current = {b.occupant for b in state.beds if b.unit_id == unit and b.occupant}
        ids = [r.stay_id for r in feed.records]
        if len(set(ids)) != len(ids):
            problems.append("duplicate_stay")
        if any(r.reviewed_at > feed.issued_at for r in feed.records):
            problems.append("future_record")
        if any(r.admitted_at is not None and r.admitted_at > r.reviewed_at for r in feed.records):
            problems.append("future_admission")
        if feed.cohort_profile and current - {
            r.stay_id for r in feed.records if r.admitted_at is not None
        }:
            problems.append("admission_clock_missing")
        valid = {
            r.stay_id
            for r in feed.records
            if r.stay_id in current
            and r.estimate
            and r.estimate >= at
            and at - timedelta(hours=24) <= r.reviewed_at <= feed.issued_at
        }
        covered, expected = len(valid), len(current)
        if state.issues:
            covered = expected = None
            problems.append("census_incomplete")
        elif 10 * covered < 9 * expected:
            problems.append("discharge_coverage")
    elif isinstance(feed, Roster):
        current_capacity = next((u.staffed_beds for u in state.units if u.id == unit), None)
        if any(b.start <= at < b.end and b.staffed_beds != current_capacity for b in feed.capacity):
            problems.append("capacity_conflict")
        if not roster_valid(feed, at, end):
            problems.append("shift_or_skill_gap")
    else:
        days = civil_days(at, end, feed.timezone)
        by_day = {d.day for d in feed.records}
        covered, expected = len(set(days) & by_day), len(days)
        if len(by_day) != len(feed.records) or covered != expected:
            problems.append("daily_coverage")
    return FeedCheck(
        kind=kind,
        source=feed.source,
        revision=feed.revision,
        issued_at=feed.issued_at,
        received_at=feed.available_at,
        synced_at=feed.synced_at,
        covers_until=feed.covers_until,
        covered=covered,
        expected=expected,
        reasons=tuple(problems),
    )


def horizon_check(state: State, unit: str, days: int) -> HorizonCheck:
    feeds = tuple(check_feed(state, unit, k, state.at + timedelta(days=days)) for k in KINDS)
    ready = not state.issues and all(not f.reasons for f in feeds)
    return HorizonCheck(days=days, feeds=feeds, data_ready=ready)


def apply_bookings(state: State) -> State:
    """The authoritative booking export replaces older demand, retaining matching prepared slots."""
    from .unit_schedule import UnitSchedule

    schedules = {x.id: x for x in state.schedules}
    for u in state.units:
        feed, _ = latest(state, u.id, "bookings")
        if not isinstance(feed, Bookings) or check_feed(state, u.id, "bookings", state.at).reasons:
            continue
        schedule = schedules.get(u.id) or UnitSchedule(id=u.id, budget_minutes=0)
        committed = {b.request.request_id: b for b in schedule.admissions if b.prepared_bed}
        rows = []
        for b in feed.records:
            old = committed.get(b.request.request_id)
            if (
                old
                and b.status == "booked"
                and not b.prepared_bed
                and old.window_start == b.window_start
                and old.window_end == b.window_end
            ):
                b = b.model_copy(update={"prepared_bed": old.prepared_bed})
            rows.append(b)
        if rows or u.id in schedules:
            schedules[u.id] = schedule.model_copy(update={"admissions": tuple(rows)})
    return state.model_copy(update={"schedules": tuple(schedules.values())})


def public_days(state: State, unit: str, days: int) -> tuple[PublicDay, ...]:
    """Known milestones even when model accuracy blocks the plan. Unknowns remain nullable."""
    start = state.at
    end = start + timedelta(days=days)
    zone = ZoneInfo("Europe/Paris")
    occupied = {b.occupant for b in state.beds if b.unit_id == unit and b.occupant}
    result = []
    for day in civil_days(start, end, "Europe/Paris"):
        first = max(start, datetime.combine(day, time.min, zone))
        stop = min(end, datetime.combine(day + timedelta(days=1), time.min, zone))
        bk, dep, capacity, em = None, None, None, None
        for kind in KINDS:
            status = check_feed(state, unit, kind, stop)
            if status.reasons:
                continue
            feed, _ = latest(state, unit, kind)
            if isinstance(feed, Bookings):
                bk = sum(
                    b.status == "booked"
                    and b.request.request_id not in occupied
                    and first <= b.request.expected_arrival < stop
                    for b in feed.records
                )
            elif isinstance(feed, Departures) and not state.issues:
                dep = sum(
                    r.stay_id in occupied
                    and r.estimate is not None
                    and first <= r.estimate < stop
                    and start - timedelta(hours=24) <= r.reviewed_at <= start
                    for r in feed.records
                )
            elif isinstance(feed, Roster):
                capacity = min(
                    (b.staffed_beds for b in feed.capacity if b.start < stop and first < b.end),
                    default=None,
                )
            elif isinstance(feed, Emergency):
                em = next((mean(d.counts) for d in feed.records if d.day == day), None)
        result.append(
            PublicDay(
                day=day,
                bookings=bk,
                estimated_departures=dep,
                min_staffed_beds=capacity,
                expected_ed_full_day=em,
            )
        )
    return tuple(result)


def staff_conflict(state: State, unit: str, offer: StaffOffer) -> bool:
    roster, _ = latest(state, unit, "roster")
    if not isinstance(roster, Roster):
        return False
    o = offer.option

    def overlapping(shift: StaffShift) -> bool:
        return shift.staff_id == offer.staff_id and shift.start < o.end and o.start < shift.end

    if any(overlapping(s) for s in roster.shifts):
        return True
    return any(
        overlapping(s)
        and not (o.source == "shared_unit" and o.lending_unit == s.unit_id and o.skill == s.skill)
        for s in roster.external_shifts or ()
    )
