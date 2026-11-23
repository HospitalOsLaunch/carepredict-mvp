"""HOWM-INT-1 intervention catalogue, commitments and budgets (fixed before any comparison).

Intervention = (kind, resource/unit, start, end, staff_hours) with admissibility:
  none        always admissible
  coord       historical action: transports requested now for authorised stays + cleaning 'compat' 24 h.
              Admissible only if it does something: an eligible stay exists or compat is not active
              (no free repetition of an executed coordination).
  cl / tr     +k shared cleaning / transport agents (k = max(1, n/2), scaled with size, decided at the qualification
              before any comparison) on an 8-h slot [06,14) or [14,22) among the first 4 slots starting >= 2 h after
              the decision (deferred plan allowed); costs 8 k staff-hours
  av          external downstream: +max(1, n/4) purchased external slots for the next 24 h (structures with M6);
              costs 8 staff-hours-equivalent (coordination with the external facility)
  staff       +1 pool nurse (IDE) for unit u on one of the first 2 slots (offer confirmation and no-show are
              exogenous, provider law)
Budgets (staff-hours): daily = 8 x n/2 (counted on the day of the slot start), weekly = 7 x daily over the
episode window. Two units: 8 h/day, 56 h/week (mandate). No stacking: at most one commitment of the same
resource (and unit for staff) on an overlapping slot. No cancellation: commitments are immutable once
issued. Budgets are read from the engine's commitments, so a planner projection never resets them.
"""

from __future__ import annotations

from typing import Any

from hospitalos.howm.world import TPD, TPH, Plan

NOTICE_TICKS = 2 * TPH
SLOT_H = 8
STAFF_H = 8


def slots(t0: int, k: int = 4) -> list[tuple[int, int]]:
    out, day = [], t0 // TPD
    while len(out) < k:
        for h in (6, 14):
            s = day * TPD + h * TPH
            if s >= t0 + NOTICE_TICKS:
                out.append((s, s + SLOT_H * TPH))
                if len(out) == k:
                    break
        day += 1
    return out


def budgets(n_units: int) -> tuple[float, float]:
    d = 8.0 * n_units / 2
    return d, 7 * d


def used_hours(eng: Any) -> tuple[dict[int, float], float]:
    per_day: dict[int, float] = {}
    for c in eng.commitments:
        per_day[c["start"] // TPD] = per_day.get(c["start"] // TPD, 0.0) + c["staff_hours"]
    return per_day, sum(per_day.values())


def _world() -> Any:
    from . import world  # lazy: world imports this module

    return world


def eligible_coord(eng: Any) -> bool:
    if any(st.departed is None and st.authorised and st.transport and not _world().transport_requested(st) for st in eng.stays.values()):
        return True
    return eng.cleaning_mode_until < eng.tick


def intensity(n_units: int) -> int:
    return max(1, n_units // 2)


def catalogue(eng: Any, units: list[str]) -> list[dict]:
    """All interventions of the current decision with their admissibility flag (same list for every policy)."""
    t0 = eng.tick
    n = len(units)
    k = intensity(n)
    sl = slots(t0, 4)
    acts = [{"kind": "none", "res": "", "unit": "", "slot": 0, "start": t0, "end": t0, "staff_hours": 0.0},
            {"kind": "coord", "res": "", "unit": "", "slot": 0, "start": t0, "end": t0 + 24 * TPH, "staff_hours": 0.0}]
    for res in ("cl", "tr"):
        for i, (a, b) in enumerate(sl):
            acts.append({"kind": res, "res": res, "unit": "", "slot": i + 1, "start": a, "end": b, "staff_hours": float(STAFF_H * k), "k": k})
    for un in units:
        for i, (a, b) in enumerate(sl[:2]):
            acts.append({"kind": "staff", "res": "staff", "unit": un, "slot": i + 1, "start": a, "end": b, "staff_hours": float(STAFF_H), "k": 1})
    if eng.spec_meta.get("aval_slots", 0) > 0:
        acts.append({"kind": "av", "res": "av", "unit": "", "slot": 0, "start": t0, "end": t0 + 24 * TPH, "staff_hours": float(STAFF_H),
                     "k": max(1, n // 4)})
    for a in acts:
        a["id"] = f"{a['kind']}{'_' + a['unit'] if a['unit'] else ''}{'_w' + str(a['slot']) if a['slot'] else ''}"
    return acts


def admissible(eng: Any, a: dict, n_units: int, window_start: int) -> bool:
    if a["kind"] == "none":
        return True
    if a["kind"] == "coord":
        return eligible_coord(eng)
    day_cap, week_cap = budgets(n_units)
    per_day, _tot = used_hours(eng)
    week = sum(v for d, v in per_day.items() if d >= window_start // TPD)
    if per_day.get(a["start"] // TPD, 0.0) + a["staff_hours"] > day_cap + 1e-9 or week + a["staff_hours"] > week_cap + 1e-9:
        return False
    for c in eng.commitments:  # no stacking of the same resource (and unit) on an overlapping slot
        if c["res"] == a["res"] and c.get("unit", "") == a["unit"] and c["start"] < a["end"] and a["start"] < c["end"]:
            return False
    return True


def apply(eng: Any, a: dict, prov: Any) -> None:
    """Execute the CURRENT intervention on an engine (true or simulated). Commitments are immutable."""
    if a["kind"] == "none":
        return
    if a["kind"] == "coord":
        eng.coord_ticks.append(eng.tick)
        eng.emit("plan", "coord", coordinate=True, cleaning="compat", reinforcement="none")
        eng.apply_plan(Plan(True, "compat", "none"), prov)
        return
    c = {"res": a["res"], "unit": a["unit"], "start": a["start"], "end": a["end"], "k": a.get("k", 1), "staff_hours": a["staff_hours"], "issued": eng.tick}
    eng.commitments.append(c)
    eng.emit("plan", f"commit_{a['id']}@{eng.tick}", commit=c)
    if a["kind"] == "staff":
        eng.add_staff(a["unit"], a["start"], a["end"], prov)


def descriptor(a: dict, t0: int) -> list[float]:
    """Explicit action descriptor (nature, resource, intensity, start, duration, staff-hours); the unit is
    given separately as a node index for the structured models."""
    return [float(a["kind"] == "none"), float(a["kind"] == "coord"), float(a["kind"] == "cl"), float(a["kind"] == "tr"),
            float(a["kind"] == "staff"), float(a["kind"] == "av"), float(a.get("k", 0)) if a["kind"] in ("cl", "tr", "staff", "av") else 0.0,
            (a["start"] - t0) / TPH, (a["end"] - a["start"]) / TPH, a["staff_hours"]]


DESC_NAMES = ("a_none", "a_coord", "a_cl", "a_tr", "a_staff", "a_av", "a_intensity", "a_start_h", "a_dur_h", "a_staff_h")
