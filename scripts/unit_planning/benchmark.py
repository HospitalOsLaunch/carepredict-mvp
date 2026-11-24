"""Prospective synthetic validation of the same no-action projection used by hybrid.plan.

Run PYTHONPATH=src:. python -m scripts.unit_planning.benchmark. Development and
measurement origins are disjoint. The source adapter receives only the observed
census, published appointments, issued ED distributions and validated shifts.
"""

from __future__ import annotations

import csv
import json
import random
import statistics
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from hospitalos.hybrid.models import Action, Bed, Discharge, Patient, State, Unit
from hospitalos.hybrid.multiday import FORECAST_VERSION, PROFILE, paired_future
from hospitalos.hybrid.outlook import (
    Bookings,
    DayDemand,
    DepartureEstimate,
    Departures,
    Emergency,
    UnitOutlook,
    apply_bookings,
    civil_days,
    horizon_check,
)
from hospitalos.hybrid.scoring import score
from hospitalos.hybrid.simulation import Assumptions, simulate
from hospitalos.hybrid.synthetic_outlook import synthetic_outlook
from hospitalos.hybrid.unit_schedule import Booking

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/operational/unit-planning-results"
UNITS = ("medecine-polyvalente", "court-sejour-geriatrique", "medecine-interne", "pneumologie")
HORIZONS = (1, 3, 7)
Z = ZoneInfo("Europe/Paris")
FIRST = date(2026, 1, 5)
# Independent seeds for generating outcomes, sampling forecasts, and resampling confidence bounds.
UNIVERSES = 8
ORIGINS = range(21, 56)
SCENARIOS = 4
BLOCK = 7
REPEATS = 2000


def clock(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(FIRST + timedelta(days=day), time(hour, minute), Z).astimezone(UTC)


def level(day: int, u: int, world: int) -> int:
    weekday = (FIRST + timedelta(days=day)).weekday()
    return 1 + int(weekday < 5) + int((day + world) % 13 < 3) + int(u == 0)


def booked(day: int, u: int) -> bool:
    return (FIRST + timedelta(days=day)).weekday() < 5 and (day + u) % 3 != 0


@dataclass(frozen=True)
class Stay:
    pid: str
    bed: int
    start: datetime
    end: datetime


def truth(u: int, world: int, cap: int) -> tuple[list[Stay], dict[int, int]]:
    rng = random.Random(40000 + 100 * world + u)
    stays = []
    free = [clock(0, 0)] * cap
    emergencies = {}
    for d in range(65):
        emergencies[d] = max(0, level(d, u, world) + rng.choice((-2, -1, 0, 0, 1, 2)))
        arrivals = [
            (clock(d, rng.randrange(7, 22), rng.randrange(60)), f"ED-{d}-{i}")
            for i in range(emergencies[d])
        ]
        if booked(d, u) and rng.random() > 0.10:
            arrivals.append((clock(d, 11, rng.randrange(30)), f"B-{d}"))
        for arrival, pid in sorted(arrivals):
            bed = min(range(cap), key=lambda i: free[i])
            start = max(arrival, free[bed])
            length = rng.choice((1, 2, 2, 3, 4, 5)) + (u == 1)
            end = datetime.combine(
                start.astimezone(Z).date() + timedelta(days=length), time(7, rng.randrange(60)), Z
            ).astimezone(UTC)
            stays.append(Stay(pid, bed, start, end))
            free[bed] = end + timedelta(minutes=rng.choice((20, 40, 60)))
    return stays, emergencies


def public_state(
    d: int, u: int, world: int, cap: int, present: dict[int, tuple[str, datetime]]
) -> State:
    # No realised departure, future occupancy or emergency count enters this function.
    at = clock(d, 8, 30)
    uid = UNITS[u]
    beds = []
    patients = []
    logistics = []
    estimates = []
    for i in range(cap):
        bid = f"L{i}"
        current = present.get(i)
        beds.append(
            Bed(
                id=bid,
                unit_id=uid,
                state="occupied" if current else "clean",
                occupant=current[0] if current else None,
            )
        )
        if current:
            pid, entered = current
            age = (at - entered).days
            cleared = age >= 2 + (u == 1)
            patients.append(
                Patient(
                    id=pid,
                    status="admitted",
                    bed_id=bid,
                    compatible_units=(uid,),
                    waiting_since=entered,
                    medically_cleared=cleared,
                )
            )
            logistics.append(
                Discharge(
                    id=pid,
                    documents_ready=True,
                    escort_required=False,
                    downstream_required=False,
                    transport_required=False,
                )
            )
            estimates.append(
                DepartureEstimate(
                    stay_id=pid, reviewed_at=at, estimate=clock(d + max(1, 3 + (u == 1) - age), 7)
                )
            )
    state = State(
        hospital_id=f"universe-{world}",
        at=at,
        fingerprint=f"u{world}.{u}.{d}",
        units=(Unit(id=uid, staffed_beds=cap, cleaning_teams=1),),
        beds=tuple(beds),
        patients=tuple(patients),
        discharges=tuple(logistics),
    )
    base = synthetic_outlook(state, uid)
    dates = civil_days(at, at + timedelta(days=7), "Europe/Paris")
    demand = []
    bookings = []
    for dt in dates:
        future = (dt - FIRST).days
        center = level(future, u, world)
        demand.append(DayDemand(day=dt, counts=(max(0, center - 1), center, center + 1)))
        if booked(future, u):
            target = clock(future, 11)
            bookings.append(
                Booking.model_validate(
                    {
                        "request": {
                            "request_id": f"B-{future}",
                            "expected_arrival": target,
                            "arrival_delay": {"support": [0], "weights": [1]},
                            "care": [],
                            "admission_task_minutes": 20,
                            "provenance": {
                                "source": "syn-bookings",
                                "obs_id": f"B-{future}",
                                "event_time": at,
                                "available_at": at,
                            },
                        },
                        "window_start": target,
                        "window_end": target + timedelta(hours=1),
                    }
                )
            )
    feeds = []
    for f in base.feeds:
        if isinstance(f, Emergency):
            f = f.model_copy(update={"records": tuple(demand)})
        if isinstance(f, Bookings):
            f = f.model_copy(update={"records": tuple(bookings)})
        if isinstance(f, Departures):
            f = f.model_copy(update={"records": tuple(estimates)})
        feeds.append(f)
    return apply_bookings(
        state.model_copy(update={"outlooks": (UnitOutlook(id=uid, feeds=tuple(feeds)),)})
    )


def study(world: int) -> tuple[list[tuple], list[tuple]]:
    rows = []
    coverage = []
    for u, uid in enumerate(UNITS):
        cap = 7 + u + world % 3
        stays, eds = truth(u, world, cap)
        census = {
            d: {s.bed: (s.pid, s.start) for s in stays if s.start <= clock(d, 8, 30) < s.end}
            for d in range(65)
        }
        for d in ORIGINS:
            state = public_state(d, u, world, cap, census[d])
            audit = horizon_check(state, uid, 7)
            dates = next(f for f in audit.feeds if f.kind == "departures")
            coverage.append((uid, dates.covered, dates.expected))
            if not audit.data_ready:
                raise ValueError("Incomplete public benchmark origin")
            ed = next(f for f in state.outlooks[0].feeds if isinstance(f, Emergency))
            ed_prediction = {r.day: statistics.mean(r.counts) for r in ed.records}
            occupied = {h: [] for h in HORIZONS}
            for scenario in range(SCENARIOS):
                tape = paired_future(state, None, 41, scenario, 10080, multiday=True)
                log = simulate(
                    state,
                    Action(kind="no_op"),
                    Assumptions(),
                    seed=41,
                    scenario=scenario,
                    horizon_minutes=10080,
                    future=tape,
                    multiday=True,
                )
                result = score(state, log, expected_future=tape)
                if result.violations:
                    raise ValueError(result.violations)
                for h in HORIZONS:
                    occupied[h].append(
                        len(census[d])
                        + sum(
                            (e.kind == "admit") - (e.kind == "depart")
                            for e in log.events
                            if e.minute <= 1440 * h
                        )
                    )
            for h in HORIZONS:
                target = d + h
                for name, pred, y, previous, weekly in (
                    (
                        "occupied",
                        statistics.mean(occupied[h]),
                        len(census[target]),
                        len(census[d]),
                        len(census[target - 7]),
                    ),
                    (
                        "emergency",
                        ed_prediction[FIRST + timedelta(days=target)],
                        eds[target],
                        eds[d - 1],
                        eds[target - (7 if h < 7 else 14)],
                    ),
                ):
                    rows.append((world, uid, d, h, name, pred, y, previous, weekly))
    return rows, coverage


def summarise(rows: list[tuple]) -> tuple[list[dict], dict[str, list[int]]]:
    rng = np.random.default_rng(7731)
    # Identical resamples across models, units and endpoints. Each sampled universe
    # carries its own resampled consecutive seven-day origin blocks and all its units.
    worlds = rng.integers(0, UNIVERSES, (REPEATS, UNIVERSES))
    blocks = rng.integers(0, len(ORIGINS) // BLOCK, (REPEATS, UNIVERSES, len(ORIGINS) // BLOCK))
    indices = (blocks[:, :, :, None] * BLOCK + np.arange(BLOCK)).reshape(
        REPEATS, UNIVERSES, len(ORIGINS)
    )
    summary = []
    passed = defaultdict(dict)
    for h in HORIZONS:
        for target in ("occupied", "emergency"):
            arr = np.empty((UNIVERSES, len(UNITS), len(ORIGINS), 3))
            for w, unit, d, hor, metric, p, y, last, weekly in rows:
                if hor == h and metric == target:
                    arr[w, UNITS.index(unit), d - ORIGINS.start] = [
                        abs(p - y),
                        abs(last - y),
                        abs(weekly - y),
                    ]
            for j, unit in enumerate((*UNITS, "all_units")):
                data = arr.mean(axis=1) if unit == "all_units" else arr[:, j]
                model, last, weekly = data.mean(axis=(0, 1))
                base = min(last, weekly)
                gain = 1 - model / base if base else None
                res = data[worlds[:, :, None], indices].mean(axis=(1, 2))
                bases = np.minimum(res[:, 1], res[:, 2])
                lo, hi = (
                    np.quantile(1 - res[:, 0] / bases, [0.025, 0.975])
                    if np.all(bases > 0)
                    else (None, None)
                )
                ok = bool(
                    gain is not None
                    and gain >= 0.1
                    and lo is not None
                    and lo > 0
                    and len(ORIGINS) >= 30
                )
                passed[unit][h, target] = ok
                summary.append(
                    {
                        "unit": unit,
                        "days": h,
                        "target": target,
                        "mae": model,
                        "persistence": last,
                        "weekly": weekly,
                        "gain": gain,
                        "low95": lo,
                        "high95": hi,
                        "passed": ok,
                    }
                )
    qualified = {
        u: [
            h
            for h in (3, 7)
            if all(
                passed[v][k, t]
                for v in (u, "all_units")
                for k in HORIZONS
                if k <= h
                for t in ("occupied", "emergency")
            )
        ]
        for u in UNITS
    }
    return summary, qualified


def main() -> None:
    with ProcessPoolExecutor(max_workers=4) as pool:
        studies = list(pool.map(study, range(UNIVERSES)))
    rows = [r for block, _ in studies for r in block]
    coverage = [r for _, block in studies for r in block]
    counted = {
        uid: {
            "covered": sum(c for u, c, n in coverage if u == uid),
            "eligible": sum(n for u, c, n in coverage if u == uid),
        }
        for uid in UNITS
    }
    summary, qualified = summarise(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "metrics.csv").open("w") as file:
        writer = csv.DictWriter(file, fieldnames=list(summary[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(summary)
    receipt = {
        "forecast_version": FORECAST_VERSION,
        "profile": PROFILE,
        "qualified_days": qualified,
        "discharge_estimates_by_unit": counted,
        "universes": UNIVERSES,
        "origins_per_universe_unit": len(ORIGINS),
        "synthetic_only": True,
        "horizon_days": HORIZONS,
        "raw_target_pairs": len(rows),
        "scenarios": SCENARIOS,
        "paired_bootstrap": {"block_days": BLOCK, "replications": REPEATS, "seed": 7731},
    }
    (ROOT / "src/hospitalos/hybrid/unit_horizon_receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n"
    )
    for row in summary:
        if row["unit"] == "all_units":
            print(row)


if __name__ == "__main__":
    main()
