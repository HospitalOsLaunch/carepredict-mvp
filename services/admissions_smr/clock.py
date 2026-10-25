"""Injectable clock so tests and replays control "now" and "today"."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo


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
