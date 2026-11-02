"""Daily indicators for the ORU (observatoire régional des urgences), per site (pure).

One row per site and day, for retrospective analysis and prediction on the regional side:

- emergency department: arrivals of the local day, and at 10:00 the patients present,
  waiting for a bed, "lits brancards à 10 h" and hosted elsewhere (``domain.ed``: a manual
  declaration of the day replaces the computed values, the computed boarding stays next to
  it, flagged by ``boarding_source``);
- units: how many are followed, in tension, critical at the end of the day, from open beds
  (dated capacity history) minus patients present at the end of the day (``domain.metrics``
  census). shortcut: ignores reservations, blocked beds and gender, which have no history;
  the live export uses the bed-level availability;
- active "HET" and "Plan blanc" declarations that day (site or whole establishment);
- the latest stored forecast of "lits brancards à 10 h" for that day, when one exists.

CSV: UTF-8 with a byte order mark (Excel), ``;`` separator, decimal comma, French headers.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from services.admissions_smr.domain.ed import DayPoint
from services.admissions_smr.domain.tension import tension_of

MAX_DAYS = 366


@dataclass(frozen=True)
class Declaration:
    kind: str  # het | plan_blanc
    level: str
    started_at: datetime
    ended_at: datetime | None


@dataclass(frozen=True)
class BoardingForecast:
    mean: float
    low: float
    high: float
    as_of: date


@dataclass(frozen=True)
class UnitLevels:
    units: int
    tension: int
    critique: int


@dataclass(frozen=True)
class OruDay:
    site_id: int
    site_name: str
    day: date
    complete: bool  # the day is over (arrivals are final)
    ed_arrivals: int | None
    present_10h: int | None
    waiting_bed_10h: int | None
    boarding_10h: int | None
    computed_boarding_10h: int | None
    boarding_source: str | None  # calcul | declaration
    hosted_elsewhere_10h: int | None
    units: int | None  # None for a day not reached yet
    units_tension: int | None
    units_critique: int | None
    het: str | None
    plan_blanc: str | None
    forecast_boarding_mean: float | None
    forecast_boarding_low: float | None
    forecast_boarding_high: float | None
    forecast_as_of: date | None


CSV_HEADERS: dict[str, str] = {
    "day": "Date",
    "site_id": "Identifiant site",
    "site_name": "Site",
    "complete": "Jour complet",
    "ed_arrivals": "Passages aux urgences",
    "present_10h": "Présents aux urgences à 10 h",
    "waiting_bed_10h": "En attente de lit à 10 h",
    "boarding_10h": "Lits brancards à 10 h",
    "computed_boarding_10h": "Lits brancards à 10 h (calculé)",
    "boarding_source": "Source lits brancards",
    "hosted_elsewhere_10h": "Hébergés hors unité à 10 h",
    "units": "Unités suivies",
    "units_tension": "Unités en tension",
    "units_critique": "Unités critiques",
    "het": "Hôpital en tension",
    "plan_blanc": "Plan blanc",
    "forecast_boarding_mean": "Prévision lits brancards 10 h (moyenne)",
    "forecast_boarding_low": "Prévision lits brancards 10 h (bas 80 %)",
    "forecast_boarding_high": "Prévision lits brancards 10 h (haut 80 %)",
    "forecast_as_of": "Prévision calculée le",
}
assert set(CSV_HEADERS) == {f.name for f in fields(OruDay)}


def days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=k) for k in range((end - start).days + 1)]


def arrivals_by_day(arrivals: Iterable[datetime], zone: ZoneInfo) -> Counter[date]:
    return Counter(a.astimezone(zone).date() for a in arrivals)


def unit_levels(
    occupancy: Mapping[date, int], capacity: Mapping[date, tuple[int, int, str]], day: date
) -> tuple[int, str] | None:
    """(installed, level) of one unit at the end of ``day``; None when it has no beds."""
    installed, beds_open, _ = capacity.get(day, (0, 0, ""))
    if installed <= 0:
        return None
    return installed, tension_of(max(0, beds_open - occupancy.get(day, 0)), installed).level


def count_levels(levels: Iterable[tuple[int, str] | None]) -> UnitLevels:
    known = [x[1] for x in levels if x is not None]
    return UnitLevels(len(known), known.count("tension"), known.count("critique"))


def active_declarations(
    declarations: Sequence[Declaration], day: date, zone: ZoneInfo
) -> dict[str, str]:
    """Level of each kind active at some point of the local day; the latest start wins."""
    start = datetime.combine(day, time(0), tzinfo=zone)
    end = start + timedelta(days=1)
    out: dict[str, str] = {}
    for d in sorted(declarations, key=lambda d: d.started_at):
        if d.started_at < end and (d.ended_at is None or d.ended_at >= start):
            out[d.kind] = d.level
    return out


def oru_day(
    site_id: int,
    site_name: str,
    day: date,
    today: date,
    ed: DayPoint | None,
    arrivals: int | None,
    levels: UnitLevels | None,
    declared: Mapping[str, str],
    forecast: BoardingForecast | None,
) -> OruDay:
    return OruDay(
        site_id=site_id,
        site_name=site_name,
        day=day,
        complete=day < today,
        ed_arrivals=arrivals,
        present_10h=ed.present if ed else None,
        waiting_bed_10h=ed.waiting_bed if ed else None,
        boarding_10h=ed.boarding if ed else None,
        computed_boarding_10h=ed.computed_boarding if ed else None,
        boarding_source=ed.source if ed else None,
        hosted_elsewhere_10h=ed.hosted_elsewhere if ed else None,
        units=levels.units if levels else None,
        units_tension=levels.tension if levels else None,
        units_critique=levels.critique if levels else None,
        het=declared.get("het"),
        plan_blanc=declared.get("plan_blanc"),
        forecast_boarding_mean=round(forecast.mean, 1) if forecast else None,
        forecast_boarding_low=round(forecast.low, 1) if forecast else None,
        forecast_boarding_high=round(forecast.high, 1) if forecast else None,
        forecast_as_of=forecast.as_of if forecast else None,
    )


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "oui" if value else "non"
    if isinstance(value, float):
        return f"{value:g}".replace(".", ",")
    if isinstance(value, date):
        return value.isoformat()
    text = str(value)
    # A cell starting with = + - @ would run as a formula in a spreadsheet (CSV injection).
    return f"'{text}" if text[:1] in ("=", "+", "-", "@") else text


def to_csv(rows: Sequence[OruDay], labels: Mapping[str, str] | None = None) -> str:
    """CSV text, BOM first. ``labels`` translates declaration levels (``niveau_1``...)."""
    names = labels or {}
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(CSV_HEADERS.values())
    for row in rows:
        values = []
        for key in CSV_HEADERS:
            value = getattr(row, key)
            if key in ("het", "plan_blanc") and isinstance(value, str):
                value = names.get(value, value)
            values.append(_cell(value))
        writer.writerow(values)
    return "﻿" + buffer.getvalue()
