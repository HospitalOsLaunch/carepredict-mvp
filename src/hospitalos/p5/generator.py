"""P5 synthetic population generator (P5-PROTO-2 §§ 2-3, 5.2, 6.1). Synthetic only.

A *structure* is a unit configuration drawn from a structure seed; a *parent episode* is a
public snapshot of that structure at ``as_of``; a *twin* B permutes the logistic vectors of
the authorised stays of the parent (A). Every draw is keyed (no sequential RNG state), so
results never depend on the order of calls. Exclusions use public criteria only and are
counted on every generated candidate before filtering.

Parameters below are synthetic design choices for a stress-test population around
UNIT_PROFILE.json; they are not validated operational values.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from hospitalos.decision_support.candidates import enumerate_plans
from hospitalos.decision_support.contracts import Plan, PublicSnapshot, SearchReport
from hospitalos.decision_support.snapshot import build_snapshot

from . import GENERATOR_VERSION

PARIS = ZoneInfo("Europe/Paris")
UTC = ZoneInfo("UTC")
AS_OF_LOCAL = datetime(2026, 11, 16, 20, 0, tzinfo=PARIS)
AS_OF = AS_OF_LOCAL.astimezone(UTC)
OBSTACLE_VOCAB = ("aval_non_confirme", "attente_resultat", "famille_injoignable")
P_PUB_GRID = (0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
MAX_STAYS, MAX_OFFERS, MAX_ADMISSIONS, MAX_PLANS = 8, 4, 4, 16
SIDECAR_SCHEMA = "HOSPITALOS_P5_REINFORCEMENT_1"
EXCLUSION_REASONS = (
    "universe_incomplete",
    "too_many_stays",
    "too_many_offers",
    "too_many_admissions",
    "twin_degenerate",
)


class GeneratorError(RuntimeError):
    """A generator defect (stop rule), never an exclusion."""


# --------------------------------------------------------------------------- keyed draws


def u01(*parts: object) -> float:
    key = "|".join(map(str, parts)).encode()
    return (int.from_bytes(hashlib.sha256(key).digest()[:8], "big") >> 11) / 2**53


def pick(u: float, seq: tuple[Any, ...] | list[Any]) -> Any:
    return seq[min(int(u * len(seq)), len(seq) - 1)]


def at(day: int, hour: int) -> datetime:
    return datetime(2026, 11, 16 + day, hour, 0, tzinfo=PARIS).astimezone(UTC)


def _iso(day: int, hour: int) -> str:
    return at(day, hour).isoformat()


def dist(*pairs: tuple[int, int]) -> dict[str, list[int]]:
    return {"support": [p[0] for p in pairs], "weights": [p[1] for p in pairs]}


def keyed_order(items: list[str], *parts: object) -> list[str]:
    return sorted(items, key=lambda x: (u01(*parts, x), x))


# --------------------------------------------------------------------------- specification


@dataclass(frozen=True)
class Logistics:
    """L_j: the logistic vector of an authorised stay (permuted between twins)."""

    destination: str
    transport_need: str
    transport_lead: tuple[tuple[int, int], ...] | None
    ready_hour: int  # local hour on day 1
    ready_delay: tuple[tuple[int, int], ...]
    planned_hour: int | None  # local hour on day 1
    obstacle: str | None

    def key(self) -> str:
        return json.dumps(self.__dict__, sort_keys=True, default=list)


@dataclass(frozen=True)
class StaySpec:
    stay_id: str
    bed_id: str
    authorized: bool
    care_day: int
    care_night: int
    task_hour: int | None  # local hour on day 1 of a 2-person task
    logistics: Logistics | None


@dataclass(frozen=True)
class OfferSpec:
    option_id: str
    skill: str
    start: tuple[int, int]
    end: tuple[int, int]
    source: str
    confirmation: str
    lending_unit: str | None
    scheduled: int | None
    minimum: int | None
    p_pub: float

    @property
    def offer_key(self) -> str:
        return offer_key_of(self.source, self.lending_unit, self.skill, at(*self.start), at(*self.end))

    @property
    def pool_key(self) -> str:
        return self.lending_unit if self.source == "shared_unit" and self.lending_unit else self.source

    @property
    def hours(self) -> int:
        return int((at(*self.end) - at(*self.start)) / timedelta(hours=1))


def offer_key_of(source: str, lender: str | None, skill: str, start: datetime, end: datetime) -> str:
    return f"{source}|{lender or '-'}|{skill}|{start.isoformat()}|{end.isoformat()}"


@dataclass(frozen=True)
class EpisodeSpec:
    partition: str
    structure_seed: int
    parent_index: int
    twin: str
    beds: tuple[tuple[str, str, tuple[str, ...], tuple[tuple[int, int], ...]], ...]  # id,status,caps,cleaning
    stays: tuple[StaySpec, ...]
    admissions: tuple[dict[str, Any], ...]
    shifts: tuple[tuple[str, int, int, int, int], ...]
    transport: tuple[int, int]
    cleaning_day0_ext: int
    offers: tuple[OfferSpec, ...]


@dataclass(frozen=True)
class Episode:
    spec: EpisodeSpec
    snapshot: PublicSnapshot
    plans: tuple[Plan, ...]
    report: SearchReport
    sidecar: Mapping[str, Mapping[str, Any]]  # offer_key -> public fields

    @property
    def universe_fingerprint(self) -> str:
        return hashlib.sha256("|".join(p.plan_id for p in self.plans).encode()).hexdigest()


@dataclass
class Candidate:
    partition: str
    structure_seed: int
    parent_index: int
    excluded: str | None
    episodes: dict[str, Episode] = field(default_factory=dict)


# --------------------------------------------------------------------------- structure


def structure_params(seed: int) -> dict[str, Any]:
    s = ("struct", seed)
    n_beds = 6 + min(int(u01(*s, "n_beds") * 3), 2)
    beds = [f"L{i:02d}" for i in range(1, n_beds + 1)]
    oxygen = [b for b in beds if u01(*s, "oxygen", b) < 0.35] or [beds[0]]
    cleaning = {
        b: ((1, pick(u01(*s, "cl_w1", b), (1, 2, 3))), (2, pick(u01(*s, "cl_w2", b), (1, 2))))
        for b in beds
    }
    lo = pick(u01(*s, "care_lo"), (15, 20))
    shifts = []
    for name, d0, h0, d1, h1, choices in (
        ("E", 0, 14, 0, 21, (2, 3)),
        ("N", 0, 21, 1, 7, (1, 2)),
        ("M", 1, 7, 1, 14, (2, 3)),
        ("P", 1, 14, 1, 21, (2, 3)),
    ):
        for i in range(pick(u01(*s, "shift", name), choices)):
            shifts.append((f"{name}{i + 1}", d0, h0, d1, h1))
    transport_cap = pick(u01(*s, "tr_cap"), (1, 2))
    transport_ext = min(transport_cap - 1, pick(u01(*s, "tr_ext"), (0, 1)))
    lender = f"U-LEND-{seed % 1000:03d}"
    sched_min = pick(u01(*s, "lender_min"), (2, 3))
    templates = [
        ("ORA", "IDE", (1, 14), (1, 20), "interim", None, None, None),
        ("ORB", "IDE", (1, 7), (1, 11), "internal_pool", None, None, None),
        ("ORC", "IDE", (1, 14), (1, 20), "shared_unit", lender, sched_min + 1, sched_min),
        ("ORD", "IDE", (1, 11), (1, 14), "internal_pool", None, None, None),
    ]
    return {
        "beds": beds,
        "oxygen": oxygen,
        "cleaning": cleaning,
        "care_lo": lo,
        "shifts": shifts,
        "transport": (transport_cap, transport_ext),
        "cleaning_day0_ext": pick(u01(*s, "cl_ext0"), (0, 1)),
        "templates": templates,
        "lender": lender,
    }


# --------------------------------------------------------------------------- parent


def _logistics(seed: int, p: int, sid: str) -> Logistics:
    k = ("parent", seed, p, "L", sid)
    need = pick(u01(*k, "need"), ("none", "none", "seated", "seated", "stretcher"))
    lead = None
    if need == "seated":
        lead = pick(u01(*k, "lead"), (((2, 1),), ((2, 1), (3, 1))))
    elif need == "stretcher":
        lead = pick(u01(*k, "lead"), (((3, 1),), ((3, 1), (4, 1))))
    return Logistics(
        destination="home" if u01(*k, "dest") < 0.6 else "facility",
        transport_need=need,
        transport_lead=lead,
        ready_hour=8 if u01(*k, "ready") < 0.4 else 11,
        ready_delay=pick(u01(*k, "delay"), (((0, 3), (1, 1)), ((0, 1), (1, 1)))),
        planned_hour=pick(u01(*k, "planned_h"), (12, 16)) if u01(*k, "planned") < 0.35 else None,
        obstacle=pick(u01(*k, "obst_code"), OBSTACLE_VOCAB) if u01(*k, "obst") < 0.35 else None,
    )


def parent_spec(partition: str, seed: int, p: int, sp: Mapping[str, Any]) -> EpisodeSpec:
    k = ("parent", seed, p)
    beds_all = list(sp["beds"])
    n_free = min(int(u01(*k, "n_free") * 3), 2)
    order = keyed_order(beds_all, *k, "bed_order")
    occupied = order[: len(order) - n_free]
    beds = []
    for b in sorted(beds_all):
        caps = ("oxygen",) if b in sp["oxygen"] else ()
        if b in occupied:
            status = "occupied"
        else:
            r = u01(*k, "free_status", b)
            status = "dirty" if r < 0.45 else ("cleaning" if r < 0.6 else "clean")
        beds.append((b, status, caps, tuple(sp["cleaning"][b])))
    stays_ids = [f"X{i:02d}" for i in range(1, len(occupied) + 1)]
    bed_of = dict(zip(stays_ids, sorted(occupied), strict=True))
    n_auth = 2 if u01(*k, "n_auth") < 0.5 else 3
    authorized = set(keyed_order(stays_ids, *k, "auth")[:n_auth])
    stays = []
    for sid in stays_ids:
        day = sp["care_lo"] + 5 * min(int(u01(*k, "care", sid) * 5), 4)
        stays.append(
            StaySpec(
                stay_id=sid,
                bed_id=bed_of[sid],
                authorized=sid in authorized,
                care_day=day,
                care_night=round(day * 0.4),
                task_hour=pick(u01(*k, "task_h", sid), (8, 9, 10, 11, 12))
                if u01(*k, "task", sid) < 0.2
                else None,
                logistics=_logistics(seed, p, sid) if sid in authorized else None,
            )
        )
    admissions = []
    for i in range(1 + min(int(u01(*k, "n_adm") * 3), 2)):
        rid = f"A{i + 1:02d}"
        day_arr = pick(u01(*k, "adm_day", rid), (0, 1, 1, 1))
        hour = pick(u01(*k, "adm_h", rid), (20, 22)) if day_arr == 0 else pick(
            u01(*k, "adm_h", rid), (8, 10, 12, 14, 16)
        )
        care = 20 + 5 * min(int(u01(*k, "adm_care", rid) * 4), 3)
        admissions.append(
            {
                "request_id": rid,
                "requirements": ["oxygen"] if u01(*k, "adm_ox", rid) < 0.4 else [],
                "expected_arrival": (day_arr, hour),
                "arrival_delay": ((0, 1), (1, 1)),
                "care_day": care,
                "care_night": round(care * 0.4),
                "admission_task_minutes": 45,
            }
        )
    return EpisodeSpec(
        partition=partition,
        structure_seed=seed,
        parent_index=p,
        twin="A",
        beds=tuple(beds),
        stays=tuple(stays),
        admissions=tuple(admissions),
        shifts=tuple(sp["shifts"]),
        transport=tuple(sp["transport"]),  # type: ignore[arg-type]
        cleaning_day0_ext=int(sp["cleaning_day0_ext"]),
        offers=(),
    )


def choose_offers(spec: EpisodeSpec, sp: Mapping[str, Any], coord_count: int) -> tuple[OfferSpec, ...]:
    """Admissible offers R chosen so that coord_count * (1 + R + R(R-1)/2) <= 16 (public)."""
    k = ("parent", spec.structure_seed, spec.parent_index)
    r_max = 0
    for r in range(4, -1, -1):
        if coord_count * (1 + r + r * (r - 1) // 2) <= MAX_PLANS:
            r_max = r
            break
    r_max = min(r_max, 3)
    n = min(int(u01(*k, "n_offers") * (r_max + 1)), r_max)
    chosen = keyed_order([t[0] for t in sp["templates"]], *k, "offer_order")[:n]
    offers = []
    for t in sp["templates"]:
        oid, skill, start, end, source, lender, sched, mini = t
        if oid not in chosen:
            continue
        confirmed = u01(*k, "confirmed", oid) < 0.35
        offers.append(
            OfferSpec(
                option_id=oid,
                skill=skill,
                start=start,
                end=end,
                source=source,
                confirmation="confirmed" if confirmed else "requested",
                lending_unit=lender,
                scheduled=sched,
                minimum=mini,
                p_pub=1.0 if confirmed else pick(u01(*k, "p_pub", oid), P_PUB_GRID),
            )
        )
    # Public, inadmissible declaration (lender at its minimum): visible, never selectable.
    if len(offers) < MAX_OFFERS and u01(*k, "inadmissible_offer") < 0.25:
        offers.append(
            OfferSpec(
                option_id="ORX",
                skill="IDE",
                start=(1, 7),
                end=(1, 14),
                source="shared_unit",
                confirmation="requested",
                lending_unit=sp["lender"] + "-B",
                scheduled=2,
                minimum=2,
                p_pub=0.5,
            )
        )
    return tuple(offers)


# --------------------------------------------------------------------------- twin


def logistics_signature(stay: StaySpec) -> str:
    return stay.logistics.key() if stay.logistics else ""


def make_twin(spec: EpisodeSpec) -> EpisodeSpec | None:
    """Circular shift sigma of L_j over authorised stays sorted by sha(stay_id)."""
    auth = sorted(
        (s for s in spec.stays if s.authorized),
        key=lambda s: hashlib.sha256(s.stay_id.encode()).hexdigest(),
    )
    if len({logistics_signature(s) for s in auth}) < 2:
        return None
    n = len(auth)
    step = 1 + min(int(u01("twin", spec.structure_seed, spec.parent_index, "step") * (n - 1)), n - 2)
    new_l = {auth[i].stay_id: auth[(i + step) % n].logistics for i in range(n)}
    stays = tuple(
        StaySpec(s.stay_id, s.bed_id, s.authorized, s.care_day, s.care_night, s.task_hour, new_l[s.stay_id])
        if s.stay_id in new_l
        else s
        for s in spec.stays
    )
    return EpisodeSpec(**{**spec.__dict__, "stays": stays, "twin": "B"})


# --------------------------------------------------------------------------- snapshot


def _obs(oid: str, kind: str, subject: str, event: datetime, value: dict[str, Any]) -> dict[str, Any]:
    return {
        "obs_id": oid,
        "kind": kind,
        "subject": subject,
        "event_time": event.isoformat(),
        "available_at": (event + timedelta(minutes=5)).isoformat(),
        "source": "p5_synthetic_generator",
        "synthetic": True,
        "value": value,
    }


def observations(spec: EpisodeSpec) -> list[dict[str, Any]]:
    o: list[dict[str, Any]] = []
    t0 = at(0, 12)
    for b, status, caps, cl in spec.beds:
        o.append(_obs(f"o-bed-{b}", "bed", b, at(0, 19), {"status": status, "capabilities": list(caps), "cleaning_hours": dist(*cl)}))
    for s in spec.stays:
        o.append(_obs(f"o-stay-{s.stay_id}", "stay", s.stay_id, at(0, 8), {"bed_id": s.bed_id, "present": True}))
        o.append(
            _obs(
                f"o-care-{s.stay_id}",
                "care_profile",
                f"{s.stay_id}.IDE",
                at(0, 18),
                {"stay_id": s.stay_id, "skill": "IDE", "day_minutes_per_hour": s.care_day, "night_minutes_per_hour": s.care_night, "status": "estimated"},
            )
        )
        o.append(
            _obs(
                f"o-auth-{s.stay_id}",
                "medical_authorization",
                s.stay_id,
                at(0, 15),
                {"status": "authorized" if s.authorized else "not_authorized", "by_role": "medecin"},
            )
        )
        if s.task_hour is not None:
            o.append(
                _obs(
                    f"o-task-{s.stay_id}",
                    "care_task",
                    f"T-{s.stay_id}",
                    at(0, 18),
                    {"stay_id": s.stay_id, "skill": "IDE", "start": _iso(1, s.task_hour), "minutes": 20, "staff_required": 2, "status": "known"},
                )
            )
        lg = s.logistics
        if lg is None:
            continue
        logi: dict[str, Any] = {"destination": lg.destination, "transport_need": lg.transport_need}
        if lg.transport_lead is not None:
            logi["transport_lead_hours"] = dist(*lg.transport_lead)
        o.append(_obs(f"o-logi-{s.stay_id}", "discharge_logistics", s.stay_id, at(0, 16), logi))
        o.append(
            _obs(
                f"o-ready-{s.stay_id}",
                "readiness_estimate",
                s.stay_id,
                at(0, 16),
                {"earliest": _iso(1, lg.ready_hour), "delay_hours": dist(*lg.ready_delay)},
            )
        )
        if lg.planned_hour is not None:
            o.append(_obs(f"o-plan-{s.stay_id}", "planned_departure", s.stay_id, at(0, 16), {"at": _iso(1, lg.planned_hour)}))
        if lg.obstacle is not None:
            o.append(
                _obs(
                    f"o-obst-{s.stay_id}",
                    "obstacle",
                    f"{s.stay_id}.obst",
                    at(0, 17),
                    {"stay_id": s.stay_id, "code": lg.obstacle, "active": True},
                )
            )
    for a in spec.admissions:
        d, h = a["expected_arrival"]
        o.append(
            _obs(
                f"o-adm-{a['request_id']}",
                "admission_request",
                a["request_id"],
                at(0, 18),
                {
                    "requirements": a["requirements"],
                    "expected_arrival": _iso(d, h),
                    "arrival_delay": dist(*a["arrival_delay"]),
                    "care": [{"skill": "IDE", "day_minutes_per_hour": a["care_day"], "night_minutes_per_hour": a["care_night"], "status": "estimated"}],
                    "admission_task_minutes": a["admission_task_minutes"],
                },
            )
        )
    for sid, d0, h0, d1, h1 in spec.shifts:
        o.append(_obs(f"o-shift-{sid}", "staff_shift", sid, t0, {"skill": "IDE", "start": _iso(d0, h0), "end": _iso(d1, h1), "status": "scheduled"}))
    o.append(_obs("o-roster-IDE", "roster_coverage", "IDE-window", t0, {"skill": "IDE", "start": _iso(0, 14), "end": _iso(1, 21)}))
    for of in spec.offers:
        value: dict[str, Any] = {
            "skill": of.skill,
            "start": _iso(*of.start),
            "end": _iso(*of.end),
            "source": of.source,
            "confirmation": of.confirmation,
        }
        if of.source == "shared_unit":
            value |= {"lending_unit": of.lending_unit, "lending_unit_scheduled": of.scheduled, "lending_unit_minimum": of.minimum}
        o.append(_obs(f"o-{of.option_id}", "reinforcement_option", of.option_id, at(0, 17), value))
    cap, ext = spec.transport
    o.append(_obs("o-team-tr", "team_capacity", "transport-d1", t0, {"team": "transport", "start": _iso(1, 8), "end": _iso(1, 18), "capacity": cap, "external_commitments": ext}))
    o.append(_obs("o-team-cl0", "team_capacity", "cleaning-d0", t0, {"team": "cleaning", "start": _iso(0, 20), "end": _iso(0, 21), "capacity": 1, "external_commitments": spec.cleaning_day0_ext}))
    o.append(_obs("o-team-cl1", "team_capacity", "cleaning-d1", t0, {"team": "cleaning", "start": _iso(1, 7), "end": _iso(1, 21), "capacity": 1, "external_commitments": 0}))
    return o


def sidecar(spec: EpisodeSpec) -> dict[str, dict[str, Any]]:
    return {
        of.offer_key: {
            "schema": SIDECAR_SCHEMA,
            "offer_key": of.offer_key,
            "p_pub": of.p_pub,
            "pool_key": of.pool_key,
            "planned_hours": of.hours,
        }
        for of in spec.offers
    }


def realise_episode(spec: EpisodeSpec, profile: Mapping[str, Any]) -> Episode:
    snapshot = build_snapshot(observations(spec), AS_OF, profile)
    if snapshot.issues:
        raise GeneratorError(f"generated snapshot has issues: {snapshot.issues}")
    plans, report = universe(snapshot, profile)
    return Episode(spec, snapshot, tuple(plans), report, sidecar(spec))


def universe(snapshot: PublicSnapshot, profile: Mapping[str, Any]) -> tuple[list[Plan], SearchReport]:
    """Same call as v6 ``recommend`` (auto mode, validity = as_of + profile minutes)."""
    start = snapshot.as_of
    end = start + timedelta(hours=int(profile["supported_horizon_hours"]))
    validity = start + timedelta(minutes=int(profile["recommendation_validity_minutes"]))
    return enumerate_plans(snapshot, profile, start, end, validity, "auto")


# --------------------------------------------------------------------------- candidates


def generate_candidate(partition: str, seed: int, p: int, profile: Mapping[str, Any], twins: bool) -> Candidate:
    sp = structure_params(seed)
    base = parent_spec(partition, seed, p, sp)
    if len(base.stays) > MAX_STAYS:
        return Candidate(partition, seed, p, "too_many_stays")
    if len(base.admissions) > MAX_ADMISSIONS:
        return Candidate(partition, seed, p, "too_many_admissions")
    bare = realise_episode(base, profile)
    coord_count = bare.report.enumerated  # no offers yet: coordination sets only
    spec = EpisodeSpec(**{**base.__dict__, "offers": choose_offers(base, sp, coord_count)})
    if len(spec.offers) > MAX_OFFERS:
        return Candidate(partition, seed, p, "too_many_offers")
    ep_a = realise_episode(spec, profile)
    if not ep_a.report.complete:
        return Candidate(partition, seed, p, "universe_incomplete")
    cand = Candidate(partition, seed, p, None, {"A": ep_a})
    if twins:
        twin = make_twin(spec)
        if twin is None:
            return Candidate(partition, seed, p, "twin_degenerate")
        ep_b = realise_episode(twin, profile)
        if not ep_b.report.complete:
            return Candidate(partition, seed, p, "universe_incomplete")
        cand.episodes["B"] = ep_b
    return cand


def generate_structure(
    partition: str,
    seed: int,
    n_parents: int,
    profile: Mapping[str, Any],
    twins: bool,
    max_candidates: int | None = None,
) -> tuple[list[Candidate], list[Candidate]]:
    """Returns (valid parents, all candidates in generation order, exclusions included)."""
    limit = max_candidates or n_parents + 50
    valid: list[Candidate] = []
    every: list[Candidate] = []
    p = 0
    while len(valid) < n_parents:
        if p >= limit:
            raise GeneratorError(f"too many exclusions in structure {seed} ({partition})")
        cand = generate_candidate(partition, seed, p, profile, twins)
        every.append(cand)
        if cand.excluded is None:
            valid.append(cand)
        p += 1
    return valid, every


def generator_info() -> dict[str, Any]:
    return {"generator_version": GENERATOR_VERSION, "as_of": AS_OF.isoformat(), "obstacle_vocab": list(OBSTACLE_VOCAB), "p_pub_grid": list(P_PUB_GRID)}
