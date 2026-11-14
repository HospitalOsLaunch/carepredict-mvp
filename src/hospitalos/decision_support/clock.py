"""UTC instants with explicit Europe/Paris civil resolution (no fixed UTC+01:00).

A civil deadline such as "tomorrow 20:00" is resolved to a UTC instant. A local time that
occurs twice (autumn change) must carry an explicit fold; one that does not exist (spring
change) is rejected. Durations are always computed between UTC instants.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")


class CivilTimeError(ValueError):
    """Raised for ambiguous or nonexistent civil times; never resolved silently."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("An explicit timezone is required")
    return value.astimezone(UTC)


def resolve_local(day: date, at: time, tz: ZoneInfo = PARIS, fold: int | None = None) -> datetime:
    """Return the UTC instant of a civil date/time, refusing silent DST guesses."""
    candidates = []
    for f in (0, 1):
        local = datetime.combine(day, at, tzinfo=tz).replace(fold=f)
        roundtrip = local.astimezone(UTC).astimezone(tz)
        if roundtrip.replace(tzinfo=None) == local.replace(tzinfo=None, fold=0):
            candidates.append(local.astimezone(UTC))
    unique = sorted(set(candidates))
    if not unique:
        raise CivilTimeError("NONEXISTENT_LOCAL_TIME", f"{day} {at} does not exist in {tz.key}")
    if len(unique) > 1:
        if fold is None:
            raise CivilTimeError(
                "AMBIGUOUS_LOCAL_TIME", f"{day} {at} occurs twice in {tz.key}; give fold=0|1"
            )
        return unique[fold]
    return unique[0]


def local_day(instant: datetime, tz: ZoneInfo = PARIS) -> date:
    return utc(instant).astimezone(tz).date()


def local_hour(instant: datetime, tz: ZoneInfo = PARIS) -> int:
    return utc(instant).astimezone(tz).hour


def hours_between(start: datetime, end: datetime) -> float:
    return (utc(end) - utc(start)) / timedelta(hours=1)


def display(instant: datetime, tz: ZoneInfo = PARIS) -> str:
    return utc(instant).astimezone(tz).strftime("%Y-%m-%d %H:%M %Z")
