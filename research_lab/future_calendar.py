"""Origin-known calendar for the synthetic v0.4.1 clock. Intervals are [start, end)."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from functools import lru_cache

RULE = "v041_fr_metropole_fixed_utc_plus_01_v1"
NATIVE_MINUTES = 15
STEPS_MINUTES = (15, 30, 60)
CLOCK = dt.timezone(dt.timedelta(hours=1))
EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)
MINUTE_NS = 60_000_000_000
FEATURES = (
    "time_sin",
    "time_cos",
    "weekday_sin",
    "weekday_cos",
    "public_holiday_fraction",
    "working_day_fraction",
    "duration_hours",
)


def check_step(minutes: int) -> int:
    if type(minutes) is not int or minutes not in STEPS_MINUTES:
        raise ValueError(f"Calendar step in minutes must be one of {STEPS_MINUTES}")
    return minutes


@lru_cache(maxsize=64)
def _holidays(year: int) -> frozenset[dt.date]:
    # Use the exact reference rules. Import lazily to keep contract checks NumPy-free.
    from hospitalos.synthetic.v041.hospsim import jours_feries

    return frozenset(jours_feries((year,)))


def civil_start(origin_ns: int) -> dt.datetime:
    if type(origin_ns) is not int or origin_ns % MINUTE_NS:
        raise ValueError("The decision origin must be an exact UTC minute")
    return (EPOCH + dt.timedelta(minutes=origin_ns // MINUTE_NS)).astimezone(CLOCK)


def calendar_grid(origin_ns: int, horizon_hours: int, step_minutes: int) -> list[tuple[float, ...]]:
    """Derive K from D alone. No simulator state, future actions or realized capacity."""
    step = check_step(step_minutes)
    if type(horizon_hours) is not int or not 1 <= horizon_hours <= 720:
        raise ValueError("Calendar horizon must be an integer from 1 to 720 hours")
    start = civil_start(origin_ns)
    rows = []
    for offset in range(0, horizon_hours * 60, step):
        at = start + dt.timedelta(minutes=offset)
        day = at.date()
        phase = math.tau * (at.hour * 60 + at.minute) / 1440
        week = math.tau * day.weekday() / 7
        # A rolling grid can straddle midnight, e.g. Friday 23:45 to Saturday 00:15.
        rest = max(0, at.hour * 60 + at.minute + step - 1440)
        holiday = day in _holidays(day.year)
        holiday_minutes = int(holiday) * (step - rest)
        working_minutes = int(day.weekday() < 5 and not holiday) * (step - rest)
        if rest:
            tomorrow = day + dt.timedelta(days=1)
            next_holiday = tomorrow in _holidays(tomorrow.year)
            holiday_minutes += int(next_holiday) * rest
            working_minutes += int(tomorrow.weekday() < 5 and not next_holiday) * rest
        rows.append(
            (
                math.sin(phase),
                math.cos(phase),
                math.sin(week),
                math.cos(week),
                holiday_minutes / step,
                working_minutes / step,
                step / 60,
            )
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True, help="ISO 8601 date and time with UTC offset")
    parser.add_argument("--step-minutes", type=int, choices=STEPS_MINUTES, default=60)
    parser.add_argument("--horizon-hours", type=int, default=24)
    args = parser.parse_args()
    try:
        origin = dt.datetime.fromisoformat(args.origin.replace("Z", "+00:00"))
        if origin.utcoffset() is None or origin.second or origin.microsecond:
            raise ValueError("Use an exact minute and an explicit UTC offset")
        delta = origin - EPOCH
        origin_ns = (delta.days * 1440 + delta.seconds // 60) * MINUTE_NS
        grid = calendar_grid(origin_ns, args.horizon_hours, args.step_minutes)
    except (ValueError, OverflowError) as exc:
        parser.error(str(exc))
    start = civil_start(origin_ns)
    step = dt.timedelta(minutes=args.step_minutes)
    print(
        json.dumps(
            {
                "rule": RULE,
                "origin": start.isoformat(),
                "step_minutes": args.step_minutes,
                "columns": FEATURES,
                "slots": [
                    {
                        "start": (start + i * step).isoformat(),
                        "end": (start + (i + 1) * step).isoformat(),
                        "values": values,
                    }
                    for i, values in enumerate(grid)
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
