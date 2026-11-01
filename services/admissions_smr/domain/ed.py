"""Emergency department census, "lits brancards à 10 h" and patients hosted elsewhere (pure).

Definitions, at an instant ``t``:

- **Présent**: arrived at or before ``t`` and not left yet (``left_at`` null or after ``t``).
  A visit counts as present at most ``STALE_AFTER`` (72 h) after arrival: beyond, a lost
  departure message is assumed rather than a three-day stay on a stretcher.
- **En attente de lit**: present, with an admission decision taken at or before ``t``.
- **Lits brancards à 10 h** for a calendar day (Europe/Paris): patients present at 10:00
  local time, with an admission decision taken by then, who arrived before 08:00 local
  time that day (``BOARDING_ARRIVED_BEFORE``), i.e. who spent the night or the early
  morning on a stretcher waiting for a bed. Arrived at 07:59 counts, 08:00 does not; left
  at 10:00 sharp is no longer present. Local times are converted with the IANA zone, so
  daylight-saving days are exact (10:00 is 08:00 UTC in summer, 09:00 UTC in winter).
  **This definition is ours and must be validated with the ARS** (LISCOP plans the
  indicator without publishing its exact rule); the cut-off is a named constant.
- **Hébergés**: patients admitted from the emergency department, still in hospital at ``t``,
  in a unit whose discipline differs from the discipline of the unit targeted by the
  emergency visit, when both are known.

Daily series: each day is read at 10:00 local time. A manual declaration (``ed_snapshots``
with source ``declaration``) made for a day replaces the computed values of that day, the
latest declaration of the day winning: it is what the hospital reports and is used when
the feed is missing or wrong. The computed boarding stays visible next to it, so a gap
between the two is seen rather than hidden.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

BOARDING_HOUR = time(10, 0)
BOARDING_ARRIVED_BEFORE = time(8, 0)
STALE_AFTER = timedelta(hours=72)


@dataclass(frozen=True)
class Visit:
    arrived_at: datetime
    admit_decision_at: datetime | None
    left_at: datetime | None


@dataclass(frozen=True)
class AdmittedStay:
    """A stay admitted from the emergency department, with the visit's target discipline."""

    admitted_at: datetime
    discharged_at: datetime | None
    discipline: str
    target_discipline: str | None


@dataclass(frozen=True)
class Census:
    at: datetime
    present: int
    waiting_bed: int
    longest_wait_hours: float | None


@dataclass(frozen=True)
class Declared:
    at: datetime
    present: int
    waiting_bed: int
    boarding: int
    hosted_elsewhere: int


@dataclass(frozen=True)
class DayPoint:
    day: date
    present: int
    waiting_bed: int
    boarding: int
    hosted_elsewhere: int
    source: str  # calcul | declaration
    computed_boarding: int


def local_time(day: date, at: time, zone: ZoneInfo) -> datetime:
    return datetime.combine(day, at, tzinfo=zone).astimezone(UTC)


def is_present(v: Visit, t: datetime) -> bool:
    return v.arrived_at <= t < v.arrived_at + STALE_AFTER and (v.left_at is None or v.left_at > t)


def is_waiting_bed(v: Visit, t: datetime) -> bool:
    return is_present(v, t) and v.admit_decision_at is not None and v.admit_decision_at <= t


def census(visits: Sequence[Visit], t: datetime) -> Census:
    waits = [
        (t - v.admit_decision_at).total_seconds() / 3600
        for v in visits
        if is_waiting_bed(v, t) and v.admit_decision_at is not None
    ]
    return Census(
        at=t,
        present=sum(is_present(v, t) for v in visits),
        waiting_bed=len(waits),
        longest_wait_hours=round(max(waits), 2) if waits else None,
    )


def boarding_10h(visits: Sequence[Visit], day: date, zone: ZoneInfo) -> int:
    t = local_time(day, BOARDING_HOUR, zone)
    cutoff = local_time(day, BOARDING_ARRIVED_BEFORE, zone)
    return sum(is_waiting_bed(v, t) and v.arrived_at < cutoff for v in visits)


def hosted_elsewhere(stays: Sequence[AdmittedStay], t: datetime) -> int:
    return sum(
        s.admitted_at <= t
        and (s.discharged_at is None or s.discharged_at > t)
        and s.target_discipline is not None
        and s.discipline != s.target_discipline
        for s in stays
    )


def daily_series(
    visits: Sequence[Visit],
    stays: Sequence[AdmittedStay],
    days: Sequence[date],
    zone: ZoneInfo,
    declarations: Sequence[Declared] = (),
) -> list[DayPoint]:
    """One point per day, read at 10:00 local time; a declaration of the day takes over."""
    ordered = sorted(visits, key=lambda v: v.arrived_at)
    arrivals = [v.arrived_at for v in ordered]
    latest: dict[date, Declared] = {}
    for d in sorted(declarations, key=lambda d: d.at):
        latest[d.at.astimezone(zone).date()] = d
    out: list[DayPoint] = []
    for day in days:
        t = local_time(day, BOARDING_HOUR, zone)
        # Only visits that arrived in the last 72 h can be present (see STALE_AFTER).
        window = ordered[bisect_left(arrivals, t - STALE_AFTER) : bisect_right(arrivals, t)]
        now = census(window, t)
        computed = boarding_10h(window, day, zone)
        declared = latest.get(day)
        if declared is not None:
            out.append(
                DayPoint(
                    day,
                    declared.present,
                    declared.waiting_bed,
                    declared.boarding,
                    declared.hosted_elsewhere,
                    "declaration",
                    computed,
                )
            )
        else:
            out.append(
                DayPoint(
                    day,
                    now.present,
                    now.waiting_bed,
                    computed,
                    hosted_elsewhere(stays, t),
                    "calcul",
                    computed,
                )
            )
    return out
