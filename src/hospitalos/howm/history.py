"""Public history builder: the ONLY path from observations to models (T-INF-01, T-PLAN-02).

An observation is used at time t iff available_at <= t (and therefore event_time <= t). The
stream is replayed in availability order; per-entity state follows the LATEST EVENT TIME known
(out-of-order deliveries never move an entity backwards). Hourly features of hour h are the state
as known at the end of hour h (NORM N6.7); the entity state at an origin t uses available_at <= t.

Identifiers are used only for joins; they never become feature values (T-INF-05). Durations
learned by the models are PUBLIC durations: from the start event's event_time to the moment the
end event becomes available (NORM N3; consistent with conditioning on "not yet observed at t").
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .world import TPH, Bed, Engine, Offer, Request, Stay, Unit

TEAMS = ("transport", "cleaning", "IDE_A", "AS_A", "IDE_B", "AS_B")
Obs = tuple[int, int, str, str, str, dict[str, Any]]
PRIVATE_KEYS = ("true_", "theta", "regime", "seed", "ekey", "establishment_id", "realisation")


@dataclass
class EntityState:
    last: int = -(10**9)  # latest event_time applied for this entity's state
    data: dict[str, Any] = field(default_factory=dict)


class PublicStream:
    """Replays observations in availability order. advance(t) applies everything available <= t."""

    def __init__(self, observations: list[Obs]):
        self.obs = sorted(observations, key=lambda o: (o[1], o[0], o[2], o[3]))
        self.i = 0
        self.t = -1
        self.static: dict[str, Any] | None = None
        self.stays: dict[str, dict[str, Any]] = {}
        self.beds: dict[str, EntityState] = {}
        self.requests: dict[str, dict[str, Any]] = {}
        self.placed_rids: set[str] = set()
        self.offers: dict[str, dict[str, Any]] = {}
        self.plans: list[tuple[int, dict[str, Any]]] = []
        self.hour_events: list[Obs] = []  # events that became available since the last take_hour()

    # --------------------------------------------------------------------------------------
    def advance(self, t_min: int) -> None:
        if t_min < self.t:
            raise ValueError("stream cannot go backwards")
        while self.i < len(self.obs) and self.obs[self.i][1] <= t_min:
            self._apply(self.obs[self.i])
            self.hour_events.append(self.obs[self.i])
            self.i += 1
        self.t = t_min

    def take_hour(self) -> list[Obs]:
        out, self.hour_events = self.hour_events, []
        return out

    def _bed(self, bed: str, ev: int, state: str, **extra: Any) -> None:
        es = self.beds.setdefault(bed, EntityState())
        if ev >= es.last:
            es.last = ev
            es.data = {"state": state, "since": ev, **extra}

    def _apply(self, o: Obs) -> None:
        ev, _avail, kind, subj, unit, v = o
        if kind == "static":
            self.static = v
            for un, d in v["units"].items():
                for b, iso in d["beds"]:
                    self.beds.setdefault(b, EntityState(data={"state": "free", "since": 0}))
            return
        if kind == "request_arrival":
            if subj not in self.placed_rids:
                self.requests[subj] = {
                    "unit": v["unit"],
                    "iso": v["iso"],
                    "acuity": v["acuity"],
                    "transport": v["transport"],
                    "arrival": ev,
                }
            return
        if kind == "placed":
            if "rid" in v:
                self.placed_rids.add(v["rid"])
                self.requests.pop(v["rid"], None)
            st = self.stays.setdefault(subj, {})
            st.update(
                {
                    "unit": v["unit"],
                    "bed": v["bed"],
                    "acuity": v["acuity"],
                    "iso": v["iso"],
                    "transport": v["transport"],
                    "placed": v.get("placed_min", ev),
                    "care": {},
                }
            )
            self._bed(v["bed"], ev, "occ", stay=subj)
            return
        st = (
            self.stays.setdefault(subj, {"care": {}})
            if kind
            in {
                "authorised",
                "ready",
                "transport_requested",
                "transport_accepted",
                "transport_start",
                "transport_done",
                "departure",
                "care_due",
            }
            else None
        )
        if st is not None:
            if kind == "care_due":
                st["care"][v["hour"]] = (v["ide"], v["as_"])
            else:
                st[kind] = ev
            if kind == "departure":
                self._bed(v["bed"], ev, "dirty", dirty=ev)
            return
        if kind == "bed_dirty":
            self._bed(subj, ev, "dirty", dirty=ev)
        elif kind == "cleaning_start":
            self._bed(subj, ev, "cleaning", clean_start=ev)
        elif kind == "cleaning_done":
            self._bed(subj, ev, "free")
        elif kind == "offer_requested":
            self.offers[subj] = {**v, "requested": ev}
        elif kind in {"offer_confirmed", "offer_present", "offer_absent"}:
            self.offers.setdefault(subj, {})[kind] = ev
        elif kind == "plan":
            self.plans.append((ev, v))

    # --------------------------------------------------------------------------------------
    def bed_units(self) -> dict[str, str]:
        assert self.static is not None
        return {b: un for un, d in self.static["units"].items() for b, _ in d["beds"]}

    def present_stays(self) -> dict[str, dict[str, Any]]:
        """Stays publicly present: placed, not departed, and still the latest occupant of their bed."""
        out = {}
        for sid, st in self.stays.items():
            if "bed" not in st or "departure" in st:
                continue
            bed = self.beds.get(st["bed"])
            if bed is None or bed.data.get("stay") != sid or bed.data.get("state") != "occ":
                continue  # implied departure (a later event on the bed is known)
            out[sid] = st
        return out

    def cohort(self, t: int) -> dict[str, list[dict[str, Any]]]:
        """Items defined by the PUBLIC state at t (NORM N3.1). Requires advance(t) first."""
        assert self.t == t
        items: dict[str, list[dict[str, Any]]] = {
            f: [] for f in ("auth", "ready", "transport", "cleaning", "confirmation", "presence")
        }
        for sid, st in sorted(self.present_stays().items()):
            prof = {
                "unit": st["unit"],
                "acuity": st["acuity"],
                "iso": st["iso"],
                "transport": st["transport"],
            }
            if "authorised" not in st:
                items["auth"].append({"ref": sid, "start": st["placed"], **prof})
            elif "ready" not in st:
                items["ready"].append({"ref": sid, "start": st["authorised"], **prof})
            if "transport_start" in st and "transport_done" not in st:
                items["transport"].append({"ref": sid, "start": st["transport_start"], **prof})
            if "transport_requested" in st and "transport_accepted" not in st:
                items["confirmation"].append(
                    {
                        "ref": f"T:{sid}",
                        "start": st["transport_requested"],
                        "kind": "transport",
                        "unit": st["unit"],
                    }
                )
        bed_unit = self.bed_units()
        for b, es in sorted(self.beds.items()):
            if es.data.get("state") == "cleaning":
                items["cleaning"].append(
                    {"ref": b, "start": es.data["clean_start"], "unit": bed_unit[b]}
                )
        for oid, of in sorted(self.offers.items()):
            if "requested" not in of:
                continue
            if of.get("source") == "pool" and "offer_confirmed" not in of:
                items["confirmation"].append(
                    {
                        "ref": f"O:{oid}",
                        "start": of["requested"],
                        "kind": "offer",
                        "unit": of["unit"],
                    }
                )
            # presence family: POOL offers only (lending presence is a public rule, always present)
            if (
                of.get("source") == "pool"
                and "offer_confirmed" in of
                and "offer_present" not in of
                and "offer_absent" not in of
                and of["start"] * 15 > t
            ):
                items["presence"].append(
                    {
                        "ref": oid,
                        "unit": of["unit"],
                        "skill": of["skill"],
                        "source": "pool" if of["source"] == "pool" else "lend",
                        "slot_start": of["start"] * 15,
                    }
                )
        return items

    # --------------------------------------------------------------------------------------
    def to_engine(self, t: int) -> Engine:
        """Public-state engine at t (private future times unknown -> None; prime with a provider)."""
        assert self.static is not None and self.t == t
        units, beds = {}, {}
        for un, d in self.static["units"].items():
            for b, iso in d["beds"]:
                beds[b] = Bed(b, un, iso)
            units[un] = Unit(
                un,
                [b for b, _ in d["beds"]],
                {k: list(v) for k, v in d["roster"].items()},
                dict(d["minimum"]),
            )
        eng = Engine(units, beds, self.static["c_tr"], self.static["c_cl"], tick=t // 15)
        eng.emit_log = False
        present = self.present_stays()
        for b, es in self.beds.items():
            bed = beds[b]
            state = es.data.get("state", "free")
            if state == "occ" and es.data.get("stay") not in present:
                state = "free"  # cannot happen by construction; defensive
            bed.state = state
            if state == "occ":
                bed.stay = es.data["stay"]
            if state in ("dirty", "cleaning"):
                bed.dirty_tick = (es.data.get("dirty", es.data["since"])) // 15
            if state == "cleaning":
                bed.clean_start = es.data["clean_start"] // 15
                bed.clean_end = 10**9  # placeholder, replaced when primed
        for sid, st in present.items():
            s = Stay(
                sid,
                st["unit"],
                st["bed"],
                st["acuity"],
                st["iso"],
                st["transport"],
                st["placed"] // 15,
            )
            s.authorised = "authorised" in st
            s.auth_tick = st["authorised"] // 15 if s.authorised else None
            s.ready = "ready" in st
            s.ready_tick = st["ready"] // 15 if s.ready else None
            if "transport_requested" in st:
                s.tr_req = st["transport_requested"] // 15
                s.tr_accepted = "transport_accepted" in st
                s.tr_conf = st["transport_accepted"] // 15 if s.tr_accepted else None
            if "transport_start" in st:
                s.tr_start = st["transport_start"] // 15
                s.tr_end = 10**9
                eng.tr_service.append(sid)
            eng.stays[sid] = s
        for rid, rq in sorted(self.requests.items(), key=lambda kv: (kv[1]["arrival"], kv[0])):
            eng.queue.setdefault(rq["unit"], []).append(
                Request(
                    rid, rq["unit"], rq["iso"], rq["acuity"], rq["transport"], rq["arrival"] // 15
                )
            )
        for oid, of in self.offers.items():
            if "requested" not in of:
                continue
            o = Offer(
                oid,
                of["unit"],
                of["skill"],
                of["source"],
                of["start"],
                of["end"],
                of["requested"] // 15,
            )
            o.confirmed = "offer_confirmed" in of
            o.conf_tick = of["offer_confirmed"] // 15 if o.confirmed else None
            if "offer_present" in of:
                o.present = True
            elif "offer_absent" in of:
                o.present = False
            eng.offers[oid] = o
        for t_plan, p in self.plans:
            if p.get("cleaning") == "compat" and t_plan // 15 + 24 * TPH > eng.tick:
                eng.cleaning_mode, eng.cleaning_mode_until = "compat", t_plan // 15 + 24 * TPH
        return eng


# ------------------------------------------------------------------------------------------
# Hourly features (B2 aggregates; H1 entity graph) — as known at the end of each hour
# ------------------------------------------------------------------------------------------
UNIT_FEATS = (
    "occ",
    "free",
    "dirty",
    "cleaning",
    "adm_queue",
    "auth_not_ready",
    "ready_wait_tr",
    "tr_pending",
    "arrivals",
    "departures",
    "cleanings_done",
    "transports_done",
    "cl_dur_mean",
    "cl_n",
    "tr_dur_mean",
    "tr_n",
    "care_ide",
    "care_as",
    "roster_ide",
    "roster_as",
    "offers_present",
    "offers_absent",
)
SHARED_FEATS = (
    "c_tr",
    "c_cl",
    "cl_busy",
    "tr_busy",
    "hsin",
    "hcos",
    "weekday",
    "plan_coord",
    "plan_compat",
    "plan_reinf",
)
B2_DIM = 2 * len(UNIT_FEATS) + len(SHARED_FEATS)
NODE_TYPES = ("stay", "bed", "unit", "team", "offer")
NODE_DIMS = {"stay": 16, "bed": 6, "unit": len(UNIT_FEATS), "team": 6, "offer": 9}
RELATIONS = ("occupies", "belongs_to", "waits_for", "serves", "reserves", "lends_to")


def clock_feats(hour: int) -> tuple[float, float, float]:
    lh = hour % 24
    return (
        math.sin(2 * math.pi * lh / 24),
        math.cos(2 * math.pi * lh / 24),
        float((hour // 24) % 7 < 5),
    )


@dataclass
class HourlyTables:
    """Per establishment: B2 matrix [H, B2_DIM]; H1 per-hour graphs; entity index (refs only for joins)."""

    b2: np.ndarray
    graphs: list[dict[str, Any]]
    n_hours: int


def hourly_tables(observations: list[Obs], n_hours: int) -> HourlyTables:
    ps = PublicStream(observations)
    rows = []
    graphs = []
    for h in range(n_hours):
        ps.advance((h + 1) * 60)  # state as known at the end of hour h
        evs = ps.take_hour()
        rows.append(_b2_row(ps, h, evs))
        graphs.append(_graph(ps, h, evs))
    return HourlyTables(np.asarray(rows, dtype=np.float32), graphs, n_hours)


def _unit_feats(ps: PublicStream, un: str, h: int, evs: list[Obs]) -> list[float]:
    assert ps.static is not None
    present = {s: st for s, st in ps.present_stays().items() if st["unit"] == un}
    beds = [b for b, _ in ps.static["units"][un]["beds"]]
    states = [ps.beds[b].data.get("state", "free") for b in beds]
    mine = [e for e in evs if e[4] == un]
    cl_d = [
        e[0] - st
        for e in mine
        if e[2] == "cleaning_done"
        for st in [_last_start(ps, e)]
        if st is not None
    ]
    tr_d = [
        e[0] - ps.stays[e[3]]["transport_start"]
        for e in mine
        if e[2] == "transport_done" and "transport_start" in ps.stays.get(e[3], {})
    ]
    care_i = sum(
        st["care"].get(h - 1, (0, 0))[0] for st in ps.stays.values() if st.get("unit") == un
    )
    care_a = sum(
        st["care"].get(h - 1, (0, 0))[1] for st in ps.stays.values() if st.get("unit") == un
    )
    roster = ps.static["units"][un]["roster"]
    offers = [o for o in ps.offers.values() if o.get("unit") == un]
    return [
        len(present) / 10,
        states.count("free") / 10,
        states.count("dirty") / 5,
        states.count("cleaning") / 5,
        sum(1 for r in ps.requests.values() if r["unit"] == un) / 5,
        sum(1 for st in present.values() if "authorised" in st and "ready" not in st) / 5,
        sum(
            1
            for st in present.values()
            if "ready" in st and st["transport"] and "transport_start" not in st
        )
        / 5,
        sum(
            1
            for st in present.values()
            if "transport_requested" in st and "transport_done" not in st
        )
        / 5,
        sum(1 for e in mine if e[2] == "request_arrival") / 3,
        sum(1 for e in mine if e[2] == "departure") / 3,
        sum(1 for e in mine if e[2] == "cleaning_done") / 3,
        sum(1 for e in mine if e[2] == "transport_done") / 3,
        (np.mean(cl_d) / 60 if cl_d else 0.0),
        len(cl_d) / 3,
        (np.mean(tr_d) / 60 if tr_d else 0.0),
        len(tr_d) / 3,
        care_i / 300,
        care_a / 300,
        roster["IDE"][h] / 5,
        roster["AS"][h] / 5,
        sum(1 for o in offers if "offer_present" in o and o["start"] // TPH <= h < o["end"] // TPH)
        / 2,
        sum(1 for o in offers if "offer_absent" in o and o["start"] // TPH <= h < o["end"] // TPH)
        / 2,
    ]


def _last_start(ps: PublicStream, e: Obs) -> int | None:
    # cleaning_done applied already -> bed state is free; start is recorded in the done event's predecessor
    # we keep the cleaning start per bed in a side table
    return ps.__dict__.setdefault("_clean_start", {}).get(e[3])


def _track_clean(ps: PublicStream, evs: list[Obs]) -> None:
    tab = ps.__dict__.setdefault("_clean_start", {})
    for e in evs:
        if e[2] == "cleaning_start":
            tab[e[3]] = e[0]


def _b2_row(ps: PublicStream, h: int, evs: list[Obs]) -> list[float]:
    assert ps.static is not None
    _track_clean(ps, evs)
    row: list[float] = []
    for un in ("A", "B"):
        row += _unit_feats(ps, un, h, evs)
    hs, hc, wd = clock_feats(h)
    plans = [p for t, p in ps.plans if h * 60 <= t < (h + 1) * 60]
    row += [
        ps.static["c_tr"] / 3,
        ps.static["c_cl"] / 2,
        sum(1 for es in ps.beds.values() if es.data.get("state") == "cleaning") / 2,
        sum(
            1
            for st in ps.present_stays().values()
            if "transport_start" in st and "transport_done" not in st
        )
        / 2,
        hs,
        hc,
        wd,
        float(any(p.get("coordinate") for p in plans)),
        float(any(p.get("cleaning") == "compat" for p in plans)),
        float(any(p.get("reinforcement") != "none" for p in plans)),
    ]
    return row


def _graph(ps: PublicStream, h: int, evs: list[Obs]) -> dict[str, Any]:
    """Entity graph as known at the end of hour h. 'refs' are join keys only (never features)."""
    assert ps.static is not None
    t = (h + 1) * 60
    nodes: dict[str, list[tuple[str, list[float]]]] = {k: [] for k in NODE_TYPES}
    edges: dict[str, list[tuple[str, str]]] = {r: [] for r in RELATIONS}
    present = ps.present_stays()
    for sid, st in sorted(present.items()):
        care = st["care"].get(h - 1, (0, 0))
        nodes["stay"].append(
            (
                sid,
                [
                    1.0,
                    float("authorised" in st),
                    float("ready" in st),
                    float("transport_requested" in st),
                    float("transport_accepted" in st),
                    float("transport_start" in st and "transport_done" not in st),
                    float(st["acuity"] == 1),
                    float(st["acuity"] == 2),
                    float(st["acuity"] == 3),
                    float(st["iso"]),
                    float(st["transport"]),
                    (t - st["placed"]) / 1440,
                    ((t - st["authorised"]) / 60 if "authorised" in st else 0.0),
                    (
                        (t - st["transport_start"]) / 60
                        if "transport_start" in st and "transport_done" not in st
                        else 0.0
                    ),
                    care[0] / 30,
                    care[1] / 30,
                ],
            )
        )
        edges["occupies"].append((f"stay:{sid}", f"bed:{st['bed']}"))
        edges["belongs_to"].append((f"stay:{sid}", f"unit:{st['unit']}"))
        if "transport_requested" in st and "transport_done" not in st:
            edges["waits_for"].append((f"stay:{sid}", "team:transport"))
    for un, d in ps.static["units"].items():
        for b, iso in d["beds"]:
            es = ps.beds[b].data
            s = es.get("state", "free")
            nodes["bed"].append(
                (
                    b,
                    [
                        float(s == "free"),
                        float(s == "occ"),
                        float(s == "dirty"),
                        float(s == "cleaning"),
                        float(iso),
                        (t - es.get("since", 0)) / 1440,
                    ],
                )
            )
            edges["belongs_to"].append((f"bed:{b}", f"unit:{un}"))
            if s in ("dirty", "cleaning"):
                edges["waits_for"].append((f"bed:{b}", "team:cleaning"))
        nodes["unit"].append((un, _unit_feats(ps, un, h, evs)))
    for team in TEAMS:
        if team == "transport":
            cap, busy = (
                ps.static["c_tr"],
                sum(
                    1
                    for st in present.values()
                    if "transport_start" in st and "transport_done" not in st
                ),
            )
            queue = sum(
                1
                for st in present.values()
                if "transport_requested" in st and "transport_start" not in st
            )
        elif team == "cleaning":
            cap, busy = (
                ps.static["c_cl"],
                sum(1 for es in ps.beds.values() if es.data.get("state") == "cleaning"),
            )
            queue = sum(1 for es in ps.beds.values() if es.data.get("state") == "dirty")
        else:
            skill, un = team.split("_")
            cap, busy, queue = ps.static["units"][un]["roster"][skill][h], 0, 0
        done = (
            sum(
                1
                for e in evs
                if e[2] == ("transport_done" if team == "transport" else "cleaning_done")
            )
            if team in ("transport", "cleaning")
            else 0
        )
        nodes["team"].append(
            (
                team,
                [
                    cap / 5,
                    busy / 3,
                    queue / 5,
                    done / 3,
                    float(team in ("transport", "cleaning")),
                    float(team.endswith("_A")),
                ],
            )
        )
        for un in ps.static["units"]:
            if team in ("transport", "cleaning") or team.endswith("_" + un):
                edges["serves"].append((f"team:{team}", f"unit:{un}"))
    for oid, of in sorted(ps.offers.items()):
        if "requested" not in of or of["end"] // TPH < h - 24:
            continue
        nodes["offer"].append(
            (
                oid,
                [
                    1.0,
                    float("offer_confirmed" in of),
                    float("offer_present" in of),
                    float("offer_absent" in of),
                    float(of["skill"] == "IDE"),
                    float(of["source"] == "pool"),
                    (of["start"] * 15 - t) / 240,
                    float(of["start"] // TPH <= h < of["end"] // TPH),
                    float(of["unit"] == "A"),
                ],
            )
        )
        edges["reserves"].append((f"offer:{oid}", f"unit:{of['unit']}"))
    edges["lends_to"] += [("unit:B", "unit:A"), ("unit:A", "unit:B")]
    return {"nodes": nodes, "edges": edges}


def assert_no_private(obj: Any) -> None:
    """T-INF-02: no private key anywhere in a serialised model input."""

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                if isinstance(k, str) and k.startswith(PRIVATE_KEYS):
                    raise AssertionError(f"private key in model input: {k}")
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)

    walk(obj)
