"""Daily series read from the database: per unit (bed pool) and per site.

Days are local calendar days (Europe/Paris by default). A series covers
[first_day, last_day], last_day being the last complete day before the forecast.

Per unit: arrivals (all modes, and split by ``stays.admission_mode``), discharges,
occupancy at the end of the day. Per site: emergency arrivals, emergency admissions
(visits that ended in a ward, counted on the day they left the emergency department)
and boarding at 10:00 ("lits brancards à 10 h", definition below).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.admissions_smr.models import BedPool, CapacityChange, EdVisit, Site, Stay

# --- Boarding at 10:00 ("lits brancards à 10 h") -------------------------------------------
# Patients present in the emergency department at 10:00 local time who have an admission
# decision taken at or before 10:00 and arrived before 08:00 that same day.
# Shared definition with the live census of the beds-ed module
# (services/admissions_smr/domain/ed.py): to unify there in one place when both merge.
BOARDING_AT = time(10, 0)
BOARDING_ARRIVED_BEFORE = time(8, 0)
# History only: a visit never closed is a data gap, not a patient boarding for months.
BOARDING_STALE_AFTER = timedelta(hours=72)

ADMISSION_MODES = ("urgences", "programme", "mutation", "transfert")
Series = npt.NDArray[np.float64]


@dataclass(frozen=True)
class SiteRef:
    site_id: int
    name: str
    ght: str | None
    departement: str | None


@dataclass(frozen=True)
class UnitRef:
    pool_id: int
    site_id: int
    code: str
    label: str
    installed: int
    open_now: int


@dataclass(frozen=True)
class StayRow:
    stay_id: int
    pool_id: int
    site_id: int
    mention: str
    admission_date: date
    admitted_day: date  # local day of admitted_at, else admission_date
    discharged_day: date | None
    planned_discharge_date: date | None


@dataclass(frozen=True)
class EdRow:
    site_id: int
    arrived_at: datetime
    admit_decision_at: datetime | None
    left_at: datetime | None
    outcome: str | None
    target_pool_id: int | None


@dataclass
class History:
    group_id: int
    zone: ZoneInfo
    first_day: date
    last_day: date
    sites: dict[int, SiteRef]
    units: dict[int, UnitRef]
    stays: list[StayRow]
    ed: list[EdRow]
    capacity: dict[int, list[tuple[date, int, int]]]  # pool -> (effective, installed, open)
    unit_series: dict[str, dict[int, Series]] = field(default_factory=dict)
    site_series: dict[str, dict[int, Series]] = field(default_factory=dict)

    @property
    def n_days(self) -> int:
        return (self.last_day - self.first_day).days + 1

    def index(self, day: date) -> int:
        return (day - self.first_day).days

    def midnight(self, day: date) -> datetime:
        return datetime.combine(day, time(0), tzinfo=self.zone).astimezone(UTC)

    def capacity_on(self, pool_id: int, day: date) -> tuple[int, int]:
        """(installed, open) beds on ``day``: the latest capacity change, else today's."""
        unit = self.units[pool_id]
        current = (unit.installed, unit.open_now)
        for effective, installed, open_ in self.capacity.get(pool_id, []):
            if effective > day:
                break
            current = (installed, open_)
        return current

    def present_at_start(self, day: date) -> dict[int, list[StayRow]]:
        """Stays in each unit at 00:00 on ``day`` (admitted before, not yet discharged)."""
        out: dict[int, list[StayRow]] = defaultdict(list)
        for s in self.stays:
            if s.admitted_day < day and (s.discharged_day is None or s.discharged_day >= day):
                out[s.pool_id].append(s)
        return out

    def ed_waiting(self, at: datetime) -> Counter[int]:
        """Emergency patients with a decision and a target unit, still waiting at ``at``."""
        out: Counter[int] = Counter()
        for v in self.ed:
            if (
                v.target_pool_id is not None
                and v.admit_decision_at is not None
                and v.admit_decision_at < at
                and (v.left_at is None or v.left_at >= at)
                and at - v.arrived_at < BOARDING_STALE_AFTER
            ):
                out[v.target_pool_id] += 1
        return out


def boarding_window(v: EdRow, zone: ZoneInfo) -> tuple[date, date] | None:
    """First and last local days on which ``v`` counts in boarding at 10:00, if any."""
    if v.admit_decision_at is None:
        return None

    def at(day: date, moment: time) -> datetime:
        return datetime.combine(day, moment, tzinfo=zone).astimezone(UTC)

    # First day d with arrival < d 08:00 and decision <= d 10:00.
    first = v.arrived_at.astimezone(zone).date()
    if v.arrived_at >= at(first, BOARDING_ARRIVED_BEFORE):
        first += timedelta(days=1)
    decided = v.admit_decision_at.astimezone(zone).date()
    if v.admit_decision_at > at(decided, BOARDING_AT):
        decided += timedelta(days=1)
    first = max(first, decided)
    # Last day d with d 10:00 < left (or before the visit goes stale).
    end = v.left_at if v.left_at is not None else v.arrived_at + BOARDING_STALE_AFTER
    last = end.astimezone(zone).date()
    if end <= at(last, BOARDING_AT):
        last -= timedelta(days=1)
    return (first, last) if first <= last else None


def load_history(session: Session, group_id: int, last_day: date, timezone: str) -> History:
    """Everything the engine needs for one group; series end on ``last_day`` included."""
    zone = ZoneInfo(timezone)

    def local(at: datetime) -> date:
        return at.astimezone(zone).date()

    sites = {
        s.id: SiteRef(s.id, s.name, s.ght, s.departement)
        for s in session.scalars(
            select(Site).where(Site.group_id == group_id, Site.active.is_(True)).order_by(Site.id)
        )
    }
    pools = list(
        session.scalars(
            select(BedPool).where(BedPool.site_id.in_(sites)).order_by(BedPool.site_id, BedPool.id)
        )
    )
    units = {
        p.id: UnitRef(
            p.id, p.site_id, p.mention, p.label or p.mention, p.beds_installed, p.beds_open
        )
        for p in pools
    }
    pool_of = {(p.site_id, p.mention): p.id for p in pools}

    capacity: dict[int, list[tuple[date, int, int]]] = defaultdict(list)
    for c in session.scalars(
        select(CapacityChange)
        .where(CapacityChange.group_id == group_id)
        .order_by(CapacityChange.effective_date, CapacityChange.id)
    ):
        if (pool_id := pool_of.get((c.site_id, c.mention))) is not None:
            capacity[pool_id].append((c.effective_date, c.beds_installed, c.beds_open))

    stays: list[StayRow] = []
    modes: list[str] = []
    for s in session.scalars(select(Stay).where(Stay.group_id == group_id)):
        pool_id = pool_of.get((s.site_id, s.mention))
        if pool_id is None:
            continue
        discharged = local(s.discharged_at) if s.discharged_at else s.discharge_date
        stays.append(
            StayRow(
                stay_id=s.id,
                pool_id=pool_id,
                site_id=s.site_id,
                mention=s.mention,
                admission_date=s.admission_date,
                admitted_day=local(s.admitted_at) if s.admitted_at else s.admission_date,
                discharged_day=discharged,
                planned_discharge_date=s.planned_discharge_date,
            )
        )
        modes.append(s.admission_mode if s.admission_mode in ADMISSION_MODES else "autre")

    ed = [
        EdRow(v.site_id, v.arrived_at, v.admit_decision_at, v.left_at, v.outcome, v.target_pool_id)
        for v in session.scalars(select(EdVisit).where(EdVisit.group_id == group_id))
        if v.site_id in sites
    ]

    # Series start with the emergency record when there is one: the stays present on its
    # first day were admitted earlier, and counting their arrivals would bias the start.
    if ed:
        first_day = min(local(v.arrived_at) for v in ed)
    else:
        first_day = min((s.admitted_day for s in stays), default=last_day)
    first_day = min(first_day, last_day)
    history = History(group_id, zone, first_day, last_day, sites, units, stays, ed, capacity)
    _fill_series(history, modes)
    return history


def _fill_series(h: History, modes: list[str]) -> None:
    n = h.n_days

    def zeros(keys: Iterable[int]) -> dict[int, Series]:
        return {k: np.zeros(n) for k in keys}

    unit = {m: zeros(h.units) for m in ("arrivals", "discharges", "occupancy")}
    unit |= {f"arrivals_{m}": zeros(h.units) for m in (*ADMISSION_MODES, "autre")}
    delta = zeros(h.units)  # occupancy changes, to integrate
    start_occupancy: Counter[int] = Counter()
    for s, mode in zip(h.stays, modes, strict=True):
        i = h.index(s.admitted_day)
        if 0 <= i < n:
            unit["arrivals"][s.pool_id][i] += 1
            unit[f"arrivals_{mode}"][s.pool_id][i] += 1
        if i < n:
            if i < 0:
                start_occupancy[s.pool_id] += 1
            else:
                delta[s.pool_id][i] += 1
        if s.discharged_day is not None:
            j = h.index(s.discharged_day)
            if 0 <= j < n:
                unit["discharges"][s.pool_id][j] += 1
            if j < 0 and i < 0:
                start_occupancy[s.pool_id] -= 1
            elif j < n:
                delta[s.pool_id][max(j, 0)] -= 1
    for pool_id in h.units:
        unit["occupancy"][pool_id] = start_occupancy[pool_id] + np.cumsum(delta[pool_id])

    with_ed = {v.site_id for v in h.ed}
    site = {m: zeros(with_ed) for m in ("ed_arrivals", "ed_admissions", "boarding_10h")}
    for v in h.ed:
        i = h.index(v.arrived_at.astimezone(h.zone).date())
        if 0 <= i < n:
            site["ed_arrivals"][v.site_id][i] += 1
        if v.outcome == "hospitalise" and v.left_at is not None:
            j = h.index(v.left_at.astimezone(h.zone).date())
            if 0 <= j < n:
                site["ed_admissions"][v.site_id][j] += 1
        window = boarding_window(v, h.zone)
        if window is not None:
            lo, hi = max(h.index(window[0]), 0), min(h.index(window[1]), n - 1)
            if lo <= hi:
                site["boarding_10h"][v.site_id][lo : hi + 1] += 1
    h.unit_series, h.site_series = unit, site
