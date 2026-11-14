"""Independent invariant checker (T-OP-01..12). It re-derives everything from the event log and
the static description; it shares NO logic with the operator (world.Engine).

Input: events as (tick, kind, subject, value) in emission order, static description, and the
hourly staff capacity the engine used. Output: list of violation strings (empty = OK).
"""

from __future__ import annotations

from typing import Any


def events_from_observations(
    obs: list[tuple[int, int, str, str, str, dict[str, Any]]],
) -> list[tuple[int, str, str, dict[str, Any]]]:
    out = []
    for ev_min, _avail, kind, subject, _unit, value in sorted(obs, key=lambda o: o[0]):
        tick = (ev_min - (60 if kind == "care_due" else 0)) // 15
        out.append((tick, kind, subject, value))
    out.sort(key=lambda e: e[0])
    return out


def initial_from_engine(eng: Any) -> dict[str, Any]:
    """State of a (public or true) engine before a rollout, for checking rollout logs."""
    return {
        "bed_state": {b: bed.state for b, bed in eng.beds.items()},
        "occupant": {b: bed.stay for b, bed in eng.beds.items() if bed.state == "occ"},
        "stay_unit": {s: st.unit for s, st in eng.stays.items() if st.departed is None},
        "authorised": {s for s, st in eng.stays.items() if st.authorised},
        "ready": {s for s, st in eng.stays.items() if st.ready},
        "accepted": {s for s, st in eng.stays.items() if st.tr_accepted},
        "in_tr": {
            s: st.tr_start
            for s, st in eng.stays.items()
            if st.tr_start is not None and st.departed is None
        },
        "in_cl": {b: bed.clean_start for b, bed in eng.beds.items() if bed.state == "cleaning"},
        "offers": {
            o: {
                "unit": of.unit,
                "skill": of.skill,
                "source": of.source,
                "start": of.start,
                "end": of.end,
            }
            for o, of in eng.offers.items()
        },
        "confirmed": {o for o, of in eng.offers.items() if of.confirmed},
        "present_tick": {o: of.start for o, of in eng.offers.items() if of.present},
    }


def check(
    events: list[tuple[int, str, str, dict[str, Any]]],
    static: dict[str, Any],
    capacity: dict[tuple[str, str, int], int] | None = None,
    start_tick: int = 0,
    initial: dict[str, Any] | None = None,
) -> list[str]:
    problems: list[str] = []
    bed_unit, bed_iso = {}, {}
    for un, d in static["units"].items():
        for b, iso in d["beds"]:
            bed_unit[b], bed_iso[b] = un, iso
    occupant: dict[str, str | None] = dict.fromkeys(bed_unit)
    bed_state: dict[str, str] = dict.fromkeys(bed_unit, "free")
    stay_bed: dict[str, str] = {}
    stay_unit: dict[str, str] = {}
    authorised, ready, departed, accepted = set(), set(), set(), set()
    req_info: dict[str, dict[str, Any]] = {}
    placed_count: dict[str, int] = dict.fromkeys(static["units"], 0)
    departed_count: dict[str, int] = dict.fromkeys(static["units"], 0)
    tr_busy: dict[int, int] = {}
    cl_busy: dict[int, int] = {}
    in_tr: dict[str, int] = {}
    in_cl: dict[str, int] = {}
    offers: dict[str, dict[str, Any]] = {}
    confirmed, present = set(), set()
    present_tick: dict[str, int] = {}

    init_occ: dict[str, int] = dict.fromkeys(static["units"], 0)
    if initial is not None:
        bed_state.update(initial["bed_state"])
        for b, sid in initial["occupant"].items():
            occupant[b] = sid
            stay_bed[sid] = b
            stay_unit[sid] = initial["stay_unit"].get(sid, bed_unit[b])
            init_occ[bed_unit[b]] += 1
        authorised |= set(initial["authorised"])
        ready |= set(initial["ready"])
        accepted |= set(initial["accepted"])
        in_tr.update({k: max(v, start_tick) for k, v in initial["in_tr"].items()})
        in_cl.update({k: max(v, start_tick) for k, v in initial["in_cl"].items()})
        offers.update(initial["offers"])
        confirmed |= set(initial["confirmed"])
        for o, t0 in initial["present_tick"].items():
            present.add(o)
            present_tick[o] = t0

    def tick_busy(table: dict[int, int], start: int, end: int) -> None:
        for t in range(start, end):
            table[t] = table.get(t, 0) + 1

    for tick, kind, subj, val in events:
        if kind == "request_arrival":
            req_info[subj] = val
        elif kind == "placed":
            bed = val["bed"]
            if bed not in bed_unit:
                problems.append(f"placed_unknown_bed:{subj}")
                continue
            if occupant[bed] is not None or bed_state[bed] != "free":
                problems.append(f"double_occupancy_or_not_free:{bed}@{tick}")
            if val.get("iso") and not bed_iso[bed]:
                problems.append(f"incompatible_bed:{subj}")
            if bed_unit[bed] != val["unit"]:
                problems.append(f"wrong_unit_bed:{subj}")
            occupant[bed], bed_state[bed] = subj, "occ"
            stay_bed[subj], stay_unit[subj] = bed, val["unit"]
            if tick >= start_tick and "placed_min" not in val:
                placed_count[val["unit"]] += 1
        elif kind == "authorised":
            authorised.add(subj)
        elif kind == "ready":
            if subj not in authorised:
                problems.append(f"ready_without_authorisation:{subj}")
            ready.add(subj)
        elif kind == "transport_start":
            if subj not in ready:
                problems.append(f"transport_before_ready:{subj}")
            if subj not in accepted:
                problems.append(f"executed_without_acceptance:{subj}")
            in_tr[subj] = tick
        elif kind == "transport_done":
            if subj not in in_tr:
                problems.append(f"transport_done_without_start:{subj}")
            else:
                tick_busy(tr_busy, in_tr.pop(subj), tick)
        elif kind == "departure":
            if subj not in authorised or subj not in ready:
                problems.append(f"departure_without_authorisation_or_readiness:{subj}")
            bed = stay_bed.get(subj)
            if bed is None or occupant[bed] != subj:
                problems.append(f"departure_not_occupant:{subj}")
            else:
                occupant[bed], bed_state[bed] = None, "dirty"
            departed.add(subj)
            departed_count[stay_unit.get(subj, "?")] = (
                departed_count.get(stay_unit.get(subj, "?"), 0) + 1
            )
        elif kind == "cleaning_start":
            if bed_state.get(subj) != "dirty":
                problems.append(f"cleaning_not_after_departure:{subj}@{tick}")
            if not 6 <= (tick % 96) // 4 < 22:
                problems.append(f"cleaning_outside_hours:{subj}@{tick}")
            bed_state[subj] = "cleaning"
            in_cl[subj] = tick
        elif kind == "cleaning_done":
            if bed_state.get(subj) != "cleaning":
                problems.append(f"cleaning_done_without_start:{subj}")
            bed_state[subj] = "free"
            tick_busy(cl_busy, in_cl.pop(subj, tick), tick)
        elif kind == "offer_requested":
            offers[subj] = val
        elif kind == "offer_confirmed":
            confirmed.add(subj)
        elif kind == "offer_present":
            if subj not in confirmed:
                problems.append(f"present_without_confirmation:{subj}")
            present.add(subj)
            present_tick[subj] = tick
        elif kind == "transport_accepted":
            accepted.add(subj)
    end = max((e[0] for e in events), default=0) + 1
    for _s, t0 in in_tr.items():
        tick_busy(tr_busy, t0, end)
    for _b, t0 in in_cl.items():
        tick_busy(cl_busy, t0, end)
    problems += [f"transport_over_capacity@{t}" for t, n in tr_busy.items() if n > static["c_tr"]]
    problems += [f"cleaning_over_capacity@{t}" for t, n in cl_busy.items() if n > static["c_cl"]]
    # conservation per unit: occupied beds = initial + placed - departed
    for un in static["units"]:
        occ = sum(1 for b, s in occupant.items() if s is not None and bed_unit[b] == un)
        init = init_occ[un] + sum(
            1 for e in events if e[1] == "placed" and "placed_min" in e[3] and e[3]["unit"] == un
        )
        if occ != init + placed_count[un] - departed_count.get(un, 0):
            problems.append(
                f"conservation:{un}:{occ}!={init}+{placed_count[un]}-{departed_count.get(un, 0)}"
            )
    # staff counted only when present; lender minimum
    if capacity is not None:
        for (un, skill, h), staff in capacity.items():
            roster = static["units"][un]["roster"][skill][h]

            def counted(
                o: str, v: dict[str, Any]
            ) -> bool:  # present, known at the start of hour h, inside the slot
                return (
                    o in present
                    and present_tick[o] <= 4 * h
                    and v["skill"] == skill
                    and v["start"] // 4 <= h < (v["end"] + 3) // 4
                )

            plus = sum(1 for o, v in offers.items() if counted(o, v) and v["unit"] == un)
            minus = sum(1 for o, v in offers.items() if counted(o, v) and v["source"] == un)
            if staff != roster + plus - minus:
                problems.append(f"staff_not_matching_presence:{un}:{skill}:{h}")
            if minus and roster - minus < static["units"][un]["minimum"][skill]:
                problems.append(f"lender_minimum:{un}:{skill}:{h}")
            if staff < 0:
                problems.append(f"negative_staff:{un}:{skill}:{h}")
    return problems
