"""Long-window projection from published schedules, ED distributions and conditional EDDs."""

from __future__ import annotations

import math
from datetime import datetime, time, timedelta
from functools import lru_cache
from importlib.resources import files
from zoneinfo import ZoneInfo

from . import flow_clock
from .innovations import draw, uniform
from .models import Patient, State
from .outlook import (
    KINDS,
    Emergency,
    HorizonCheck,
    Roster,
    civil_days,
    horizon_check,
    latest,
    public_days,
)
from .scenarios import FutureArrival, FutureAssumptions, FutureTape, ResourceChange, sample_future

FORECAST_VERSION = "unit-flow-v1"
PROFILE = "direct-to-beneficiary-v1"


@lru_cache(maxsize=1)
def qualified_units(version: str = FORECAST_VERSION) -> dict[str, list[int]]:
    import json

    try:
        filename = (
            "unit_flow_v2_receipt.json"
            if version == flow_clock.VERSION
            else "unit_horizon_receipt.json"
        )
        receipt = json.loads(files(__package__).joinpath(filename).read_text())
        if (
            receipt["forecast_version"] != version
            or receipt["profile"] != PROFILE
            or receipt["synthetic_only"] is not True
        ):
            return {}
        by_unit = receipt["qualified_days"]
        if not isinstance(by_unit, dict) or any(
            v not in ([], [3], [3, 7]) for v in by_unit.values()
        ):
            return {}
        return dict(by_unit)
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def assess_horizon(state: State, unit: str, days: int) -> HorizonCheck:
    result = horizon_check(state, unit, days)
    ed, _ = latest(state, unit, "emergency")
    same_profile = (
        isinstance(ed, Emergency)
        and ed.allocation_rule == PROFILE
        and all(
            feed is not None and feed.provenance == "synthetic"
            for kind in KINDS
            for feed, _ in [latest(state, unit, kind)]
        )
    )
    cohort = flow_clock.declared(state)
    evidence = qualified_units(flow_clock.VERSION) if cohort else qualified_units()
    if cohort:
        same_profile = same_profile and flow_clock.available(state, days * 1440)
    known = same_profile and unit in evidence
    qualified = bool(known and days in evidence[unit])
    reasons = ([] if result.data_ready else ["source_gate"]) + (
        [] if qualified else ["accuracy_gate" if known else "qualification_missing"]
    )
    if cohort:
        qualified = False
        reasons.append("cohort_ranking_unqualified")
    return result.model_copy(
        update={
            "qualified": qualified,
            "reasons": tuple(reasons),
            "perspective": public_days(state, unit, days),
        }
    )


def recheck_horizon(state: State, unit: str | None, minutes: int) -> None:
    if minutes > 1440:
        check = assess_horizon(state, unit or "", minutes // 1440)
        if not (check.qualified and check.data_ready):
            raise ValueError("Planning sources or qualification expired; replan")


def forecast_state(state: State, unit: str) -> State:
    roster, _ = latest(state, unit, "roster")
    if not isinstance(roster, Roster):
        raise ValueError("Validated roster required")
    active = next(b for b in roster.capacity if b.start <= state.at < b.end)
    # Reconcile capacity at D against the observed staffed beds. A future roster
    # may change the limit at its next boundary; the observed census is retained.
    if active.staffed_beds != next(u.staffed_beds for u in state.units if u.id == unit):
        raise ValueError("Roster capacity at origin disagrees with observed unit")
    return state


def paired_future(
    state: State,
    spec: FutureAssumptions | None,
    seed: int,
    scenario: int,
    horizon: int,
    *,
    multiday: bool,
) -> FutureTape:
    use_cohort = flow_clock.available(state, horizon)
    if not multiday and not use_cohort:
        return sample_future(state, spec, seed, scenario)
    unit = state.units[0].id
    ed, _ = latest(state, unit, "emergency")
    roster, _ = latest(state, unit, "roster")
    if not isinstance(ed, Emergency) or not isinstance(roster, Roster):
        raise ValueError("Long projection requires both ED forecast and roster")
    forecast_state(state, unit)
    # Published ED demand replaces the generic ED scenario. Planned demand remains paired.
    tape = sample_future(
        state, spec.model_copy(update={"arrivals": ()}) if spec else None, seed, scenario
    )
    events = list(tape.events)
    end = state.at + timedelta(minutes=horizon)
    changes = {
        (e.minute, e.target_id)
        for e in events
        if isinstance(e, ResourceChange) and e.resource == "staffed_beds"
    }
    for b in roster.capacity:
        minute = math.ceil((b.start - state.at).total_seconds() / 60)
        if 0 < minute <= horizon and (minute, unit) not in changes:
            events.append(
                ResourceChange(
                    id=f"roster:{minute}",
                    minute=minute,
                    target_id=unit,
                    resource="staffed_beds",
                    capacity=b.staffed_beds,
                )
            )
    zone = ZoneInfo(ed.timezone)
    days = set(civil_days(state.at, end, ed.timezone))
    for row in ed.records:
        if row.day not in days:
            continue
        start = datetime.combine(row.day, time.min, zone).astimezone(state.at.tzinfo)
        stop = datetime.combine(row.day + timedelta(days=1), time.min, zone).astimezone(
            state.at.tzinfo
        )
        if use_cohort:
            # Published daily totals, with the synthetic generator's daytime arrival window.
            start = datetime.combine(row.day, time(7), zone).astimezone(state.at.tzinfo)
            stop = datetime.combine(row.day, time(22), zone).astimezone(state.at.tzinfo)
        key = f"{state.hospital_id}:{unit}:{row.day.isoformat()}"
        count = draw(row.counts, seed, scenario, "ed-count", key)
        for index in range(count):
            fraction = (index + uniform(seed, scenario, "ed-time", f"{key}:{index}")) / count
            at = start + (stop - start) * fraction
            minute = math.ceil((at - state.at).total_seconds() / 60)
            if 0 < minute <= horizon:
                pid = f"ed:{row.day}:{index}"
                events.append(
                    FutureArrival(
                        id=pid,
                        minute=minute,
                        patient=Patient(
                            id=pid,
                            status="waiting",
                            compatible_units=(unit,),
                            waiting_since=state.at + timedelta(minutes=minute),
                        ),
                    )
                )
    feed = flow_clock.declared(state) if use_cohort else None
    clock = flow_clock.CohortClock.from_feed(state, feed, seed, scenario) if feed else None
    return FutureTape(state.at, tuple(sorted(events, key=lambda e: (e.minute, e.id))), clock)
