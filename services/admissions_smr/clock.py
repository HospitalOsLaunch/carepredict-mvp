"""Injectable clock so tests and replays control "now" and "today"."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo


def local_time(day: date, at: time, zone: ZoneInfo) -> datetime:
    """The UTC instant of ``at`` local time on ``day`` (daylight saving handled by the zone)."""
    return datetime.combine(day, at, tzinfo=zone).astimezone(UTC)


def local_day(at: datetime, zone: ZoneInfo) -> date:
    """The local calendar day of an aware instant."""
    return at.astimezone(zone).date()


def horizon_label(day: date, today: date) -> str:
    """ "J+n" counted from today, never from a run's own date: a day of a stale run that is
    already past reads "J-1", so the forecast page and the ROR export always agree."""
    return f"J{(day - today).days:+d}"


class Clock:
    def __init__(self, timezone: str = "Europe/Paris") -> None:
        self.zone = ZoneInfo(timezone)

    def now(self) -> datetime:
        return datetime.now(UTC)

    def today(self) -> date:
        return self.now().astimezone(self.zone).date()


class FrozenClock(Clock):
    def __init__(self, at: datetime, timezone: str = "Europe/Paris") -> None:
        super().__init__(timezone)
        if at.tzinfo is None:
            raise ValueError("FrozenClock needs a timezone-aware datetime")
        self.at = at.astimezone(UTC)

    def now(self) -> datetime:
        return self.at
