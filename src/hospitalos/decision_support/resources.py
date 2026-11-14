"""Resources: skills, slots, external commitments, idempotent local reservations.

Staffing is computed per skill and per hour with simultaneous presence; a total of hours is
never used to compensate a missing skill or a missing simultaneous presence (T12). A
reinforcement taken from another unit is refused when it breaks that unit's declared minimum
and is refused when that commitment is unknown (T13). A requested but unconfirmed
reinforcement is conditional, never counted as present in the confirmed result (T11).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .contracts import PublicSnapshot, ReinforcementOption, TeamCapacity


def hour_index(start: datetime, at: datetime) -> int:
    return math.floor((at - start) / timedelta(hours=1))


def hour_index_ceil(start: datetime, at: datetime) -> int:
    """Conservative index for 'not before' times (readiness, planned departure): a time with
    minutes is moved to the NEXT whole hour, never earlier than what was observed."""
    return math.ceil((at - start) / timedelta(hours=1))


def lending_violations(
    options: tuple[ReinforcementOption, ...] | list[ReinforcementOption],
) -> list[str]:
    """F02: cumulative check of loans taken from the same unit, skill and hour.

    Each option may respect the lender's minimum on its own; together they must too. When
    options of one lender declare different staffing figures, the most conservative pair is
    used (lowest scheduled, highest minimum).
    """
    per_hour: dict[tuple[str, str, datetime], list[ReinforcementOption]] = {}
    for o in options:
        if o.source != "shared_unit" or o.lending_unit is None:
            continue
        h = o.start
        while h < o.end:
            per_hour.setdefault((o.lending_unit, o.skill, h), []).append(o)
            h += timedelta(hours=1)
    problems = []
    for (unit, skill, h), taken in sorted(per_hour.items()):
        scheduled = [o.lending_unit_scheduled for o in taken]
        minimum = [o.lending_unit_minimum for o in taken]
        if any(v is None for v in scheduled + minimum):
            problems.append(f"lending_unit_commitment_unknown:{unit}:{skill}:{h.isoformat()}")
            continue
        sched, mini = min(scheduled), max(minimum)  # type: ignore[type-var]
        if sched - len(taken) < mini:  # type: ignore[operator]
            ids = "+".join(sorted(o.option_id for o in taken))
            problems.append(
                f"lending_unit_minimum_cumulative:{unit}:{skill}:{h.isoformat()}:"
                f"{sched}-{len(taken)}<{mini}:{ids}"
            )
    return problems


def covers(window_start: datetime, window_end: datetime, hour_start: datetime) -> bool:
    return window_start <= hour_start and hour_start + timedelta(hours=1) <= window_end


def option_admissibility(
    option: ReinforcementOption, horizon_start: datetime, horizon_end: datetime
) -> tuple[bool, str]:
    if option.end <= option.start:
        return False, "empty_window"
    if option.start < horizon_start or option.end > horizon_end:
        return False, "outside_supported_horizon"
    if option.confirmation == "unknown":
        return False, "confirmation_unknown"
    if option.source == "shared_unit":
        if option.lending_unit_scheduled is None or option.lending_unit_minimum is None:
            return False, "external_commitment_unknown"
        if option.lending_unit_scheduled - 1 < option.lending_unit_minimum:
            return False, (
                f"violates_lending_unit_minimum:{option.lending_unit}:"
                f"{option.lending_unit_scheduled}-1<{option.lending_unit_minimum}"
            )
        return True, (
            f"external_cost:{option.lending_unit}:remaining_margin="
            f"{option.lending_unit_scheduled - 1 - option.lending_unit_minimum}"
        )
    return True, "ok"


def team_capacity(
    teams: tuple[TeamCapacity, ...], team: str, start: datetime, hours: int
) -> tuple[list[int], list[bool]]:
    """Residual capacity per hour (capacity - external commitments) and 'known' flags.

    Hours not covered by any declaration have capacity 0 and are marked unknown; an unknown
    capacity is never treated as available.
    """
    capacity = [0] * hours
    known = [False] * hours
    for h in range(hours):
        hour_start = start + timedelta(hours=h)
        for t in teams:
            if t.team != team or not covers(t.start, t.end, hour_start):
                continue
            if t.capacity is None or t.external_commitments is None:
                continue
            capacity[h] = max(0, t.capacity - t.external_commitments)
            known[h] = True
    return capacity, known


def roster_known(snapshot: PublicSnapshot, skill: str, start: datetime, hours: int) -> list[bool]:
    return [
        any(
            c.skill == skill and covers(c.start, c.end, start + timedelta(hours=h))
            for c in snapshot.roster_coverage
        )
        for h in range(hours)
    ]


def staff_per_hour(
    snapshot: PublicSnapshot,
    skill: str,
    start: datetime,
    hours: int,
    reinforcements: tuple[ReinforcementOption, ...] = (),
) -> tuple[list[int], list[int]]:
    scheduled = [0] * hours
    extra = [0] * hours
    for h in range(hours):
        hour_start = start + timedelta(hours=h)
        scheduled[h] = sum(
            s.skill == skill and covers(s.start, s.end, hour_start) for s in snapshot.shifts
        )
        extra[h] = sum(
            r.skill == skill and covers(r.start, r.end, hour_start) for r in reinforcements
        )
    return scheduled, extra


@dataclass(frozen=True)
class CoverageHour:
    demand_minutes: int  # staff-minutes including tasks impossible to staff simultaneously
    uncovered_minutes: int
    simultaneity_shortfall_minutes: int
    staff_required: int


def coverage(base_minutes: int, tasks: list[tuple[int, int]], staff: int) -> CoverageHour:
    """tasks: (minutes, simultaneous staff). Capacity is 60 staff-minutes per present person.

    A task needing more simultaneous staff than present is uncovered as a whole: it is not
    compensated by spare minutes of the present staff.
    """
    feasible = sum(m * k for m, k in tasks if k <= staff)
    shortfall = sum(m * k for m, k in tasks if k > staff)
    required = base_minutes + feasible
    uncovered = max(0, required - 60 * staff) + shortfall
    demand = required + shortfall
    needed = max([math.ceil(demand / 60)] + [k for _, k in tasks]) if demand else 0
    return CoverageHour(demand, uncovered, shortfall, needed)


@dataclass
class ResourceLedger:
    """Local, idempotent reservations for the demo review step (no external system)."""

    capacity: dict[tuple[str, str], int] = field(default_factory=dict)
    by_key: dict[str, tuple[str, str]] = field(default_factory=dict)
    used: dict[tuple[str, str], list[str]] = field(default_factory=dict)

    def reserve_all(
        self, requests: list[tuple[str, str, str, int | None]]
    ) -> tuple[bool, list[str]]:
        """F03: all-or-nothing. Requests are (resource, slot, key, capacity if known).

        Everything is checked on a staged copy first; the ledger is changed only if every
        request succeeds, so a refused plan leaves no new commitment and touches no
        reservation held by another request.
        """
        staged = ResourceLedger(
            capacity=dict(self.capacity),
            by_key=dict(self.by_key),
            used={k: list(v) for k, v in self.used.items()},
        )
        details = []
        ok_all = True
        for resource, slot, key, cap in requests:
            if cap is not None:
                staged.capacity.setdefault((resource, slot), cap)
            ok, why = staged.reserve(resource, slot, key)
            details.append(f"{resource}@{slot}:{why}")
            ok_all = ok_all and ok
        if ok_all:
            self.capacity, self.by_key, self.used = staged.capacity, staged.by_key, staged.used
        return ok_all, details

    def reserve(self, resource: str, slot: str, key: str) -> tuple[bool, str]:
        if key in self.by_key:
            if self.by_key[key] != (resource, slot):
                return False, "idempotency_key_reused_for_other_resource"
            return True, "duplicate_ignored"
        cap = self.capacity.get((resource, slot))
        if cap is None:
            return False, "capacity_unknown"
        holders = self.used.setdefault((resource, slot), [])
        if len(holders) >= cap:
            return False, "capacity_exhausted"
        holders.append(key)
        self.by_key[key] = (resource, slot)
        return True, "reserved"
