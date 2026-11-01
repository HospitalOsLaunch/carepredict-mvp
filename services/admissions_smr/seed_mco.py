"""Synthetic MCO demo hospital for the LISCOP modules (beds, emergency department, forecasts).

A fictitious general hospital of département 59 and its SMR site: units, rooms and beds,
one year of emergency visits and stays fed as if by HL7 movements. Deterministic for a
given ``now`` and ``seed``. No real identity: references are random 64-hex tokens (the
shape of an HMAC), ages are in years, staff accounts are named after their role.

The emergency flow drives the wards: an admitted patient waits in the emergency department
until a bed of the target unit is free (discharges happen during the day), so boarding at
10:00 appears on its own when wards are full, mostly during the winter epidemic.
"""

from __future__ import annotations

import heapq
import math
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import insert
from sqlalchemy.orm import Session

from services.admissions_smr.models import (
    Bed,
    BedPool,
    CapacityChange,
    EdVisit,
    Group,
    Site,
    StaffPlan,
    Stay,
    User,
)
from services.admissions_smr.security import hash_password
from services.admissions_smr.seed import CARE_LEVEL_WEIGHTS, _poisson
from services.admissions_smr.vocab import CAPACITY_REASONS, UNIT_KINDS

GROUP_NAME = "Centre hospitalier des Deux-Rivières (fictif)"
GHT = "GHT Hainaut-Fictif"
DEPARTEMENT = "59"
TERRITORY = "Hainaut"
EMAIL_DOMAIN = "ch-demo.hospitalos.fr"
HISTORY_DAYS = 365
ED_DAILY_MEAN = 120.0
CLEANING = timedelta(hours=1)
MAX_BOARDING = timedelta(hours=30)  # beyond, the patient is transferred elsewhere


@dataclass(frozen=True)
class UnitSpec:
    code: str
    label: str
    uf_code: str
    installed: int
    single_share: float  # share of beds in single rooms (the rest in double rooms)
    los: tuple[float, float]  # mean length of stay (days), gamma shape
    planned_per_weekday: float  # programmed admissions (or SMR admissions) per weekday
    mutation_share: float = 0.0  # share of planned admissions that come from another unit
    closures: tuple[tuple[int, int | None, int, str], ...] = ()  # (from, until, beds, reason)


MCO_SITE = "CH Deux-Rivières"
SMR_SITE = "SMR Les Saules"
SMR_CODES = frozenset({"polyvalent", "geriatrie"})
ELDERLY_UNITS = frozenset({"court_sejour_geriatrique", "geriatrie"})

UNITS: dict[str, list[UnitSpec]] = {
    MCO_SITE: [
        # The emergency department has no hospitalisation beds here: ed_visits describe it.
        UnitSpec("urgences", "Urgences", "1001", 0, 1.0, (0.2, 1.0), 0.0),
        UnitSpec(
            "medecine_polyvalente",
            "Médecine polyvalente",
            "2101",
            36,
            0.4,
            (5.0, 2.0),
            0.6,
            1.0,
            ((45, None, 2, "personnel"),),
        ),
        UnitSpec(
            "court_sejour_geriatrique",
            "Court séjour gériatrique",
            "2201",
            30,
            0.4,
            (7.0, 2.0),
            0.3,
            1.0,
        ),
        UnitSpec(
            "cardiologie",
            "Cardiologie",
            "2301",
            28,
            0.4,
            (3.8, 2.2),
            2.0,
            0.2,
            ((25, None, 2, "travaux"),),
        ),
        UnitSpec(
            "chirurgie_viscerale",
            "Chirurgie viscérale",
            "3101",
            26,
            0.5,
            (4.0, 2.0),
            2.0,
            0.0,
            ((120, 90, 6, "saisonnier"),),
        ),
        UnitSpec(
            "chirurgie_orthopedique",
            "Chirurgie orthopédique",
            "3201",
            26,
            0.5,
            (3.5, 2.4),
            2.5,
        ),
        UnitSpec("reanimation", "Réanimation", "4001", 12, 1.0, (5.0, 1.6), 0.3),
    ],
    SMR_SITE: [
        UnitSpec("polyvalent", "SMR polyvalent", "5101", 50, 0.5, (24.0, 2.2), 2.6, 0.7),
        UnitSpec("geriatrie", "SMR gériatrie", "5201", 40, 0.5, (30.0, 2.0), 1.7, 0.7),
    ],
}

# Share of emergency admissions per unit, by age band (balanced with the units' capacity).
ED_TARGETS_ELDERLY = {
    "court_sejour_geriatrique": 0.36,
    "medecine_polyvalente": 0.31,
    "cardiologie": 0.15,
    "chirurgie_orthopedique": 0.12,
    "reanimation": 0.06,
}
ED_TARGETS_ADULT = {
    "medecine_polyvalente": 0.22,
    "cardiologie": 0.24,
    "chirurgie_viscerale": 0.24,
    "chirurgie_orthopedique": 0.18,
    "reanimation": 0.12,
}
# Arrivals per hour of the day (relative), with the late-morning and evening peaks.
HOURLY = [
    2,
    1.5,
    1.2,
    1,
    1,
    1.2,
    2,
    3.5,
    5.5,
    7,
    7.5,
    7,
    6.5,
    6.5,
    6.5,
    6.5,
    6.5,
    7,
    7,
    6.5,
    6,
    5,
    4,
    3,
]
WEEKDAY = [1.12, 1.02, 0.98, 0.96, 1.0, 0.95, 0.97]
STAFF = [
    ("bedmanager", "Gestion des lits (démo)", "coordination"),
    ("cadre", "Cadre de santé (démo)", "coordination"),
    ("direction", "Direction (démo)", "direction"),
    ("admin", "Administration (démo)", "admin_groupe"),
    ("agent", "Agent d'ingestion", "ingestion"),
]


def _season(day: date) -> float:
    """Yearly cycle (winter high) times a winter epidemic wave centred on 15 January."""
    doy = day.timetuple().tm_yday
    yearly = 1 + 0.05 * math.cos(2 * math.pi * (doy - 15) / 365.25)
    peak = date(day.year if day.month < 7 else day.year + 1, 1, 15)
    wave = 0.18 * math.exp(-(((day - peak).days / 16) ** 2) / 2)
    return yearly + wave


@dataclass
class Ward:
    pool: BedPool
    spec: UnitSpec
    occupants: list[datetime]  # heap of discharge times (beds taken or promised)

    def capacity(self, days_before: int) -> int:
        closed = sum(
            beds
            for start, end, beds, _ in self.spec.closures
            if days_before <= start and (end is None or days_before > end)
        )
        return self.spec.installed - closed

    def take_bed(self, at: datetime, days_before: int, max_wait: timedelta) -> datetime | None:
        """When the patient gets a bed: now, at the next discharge within ``max_wait``, or None."""
        while self.occupants and self.occupants[0] <= at:
            heapq.heappop(self.occupants)
        if len(self.occupants) < self.capacity(days_before):
            return at
        if not self.occupants or self.occupants[0] + CLEANING - at > max_wait:
            return None
        return heapq.heappop(self.occupants) + CLEANING


def seed_demo_mco(
    session: Session,
    now: datetime,
    password: str,
    password_iterations: int,
    timezone: str = "Europe/Paris",
    seed: int = 59,
) -> Group:
    rng = random.Random(seed)
    zone = ZoneInfo(timezone)
    today = now.astimezone(zone).date()
    start = today - timedelta(days=HISTORY_DAYS)

    def token() -> str:
        return f"{rng.getrandbits(256):064x}"

    def local(at: datetime) -> date:
        return at.astimezone(zone).date()

    def midnight(day: date) -> datetime:
        return datetime.combine(day, time(0), tzinfo=zone).astimezone(UTC)

    group = Group(name=GROUP_NAME, created_at=now)
    session.add(group)
    session.flush()

    wards: dict[str, Ward] = {}
    sites: dict[str, Site] = {}
    for site_name, specs in UNITS.items():
        site = Site(
            group_id=group.id,
            name=site_name,
            city="Deux-Rivières",
            capabilities="oxygene",
            ght=GHT,
            departement=DEPARTEMENT,
            territory=TERRITORY,
            created_at=now,
        )
        session.add(site)
        session.flush()
        sites[site_name] = site
        for spec in specs:
            unit_type, discipline = UNIT_KINDS.get(spec.code, ("smr", "smr"))
            pool = BedPool(
                site_id=site.id,
                mention=spec.code,
                beds_installed=spec.installed,
                beds_open=spec.installed,
                isolation_rooms=0,
                unit_type=unit_type,
                discipline=discipline,
                label=spec.label,
                uf_code=spec.uf_code,
                updated_at=now,
            )
            site.pools.append(pool)
            wards[spec.code] = Ward(pool, spec, [])
            pool.beds_open = wards[spec.code].capacity(0)
            _add_capacity_history(session, group, wards[spec.code], today, now)
    session.flush()

    stays: list[dict[str, Any]] = []
    visits: list[dict[str, Any]] = []

    def discharge_after(admitted: datetime, spec: UnitSpec) -> datetime:
        mean, shape = spec.los
        days = rng.gammavariate(shape, mean / shape)
        day = local(admitted + timedelta(days=days))
        if day.weekday() >= 5 and rng.random() < 0.6:
            day += timedelta(days=7 - day.weekday())
        hour = min(18.0, max(10.0, rng.gauss(13.5, 1.8)))
        return max(midnight(day) + timedelta(hours=hour), admitted + timedelta(hours=6))

    def add_stay(
        ward: Ward, admitted: datetime, mode: str, encounter: str, patient: str, sex: str, age: int
    ) -> None:
        discharged = discharge_after(admitted, ward.spec)
        heapq.heappush(ward.occupants, discharged)
        if admitted > now:
            return
        gone = discharged <= now
        planned = None  # entered by the team for about 6 present stays in 10, may slip
        if not gone and rng.random() < 0.6:
            slip = rng.choice([0, 0, 0, 1, -1, 2])
            planned = max(today, local(discharged) + timedelta(days=slip))
        stays.append(
            {
                "group_id": group.id,
                "site_id": ward.pool.site_id,
                "mention": ward.spec.code,
                "patient_ref": patient,
                "encounter_ref": encounter,
                "patient_sex": sex,
                "patient_age": age,
                "admission_date": local(admitted),
                "admitted_at": admitted,
                "discharge_date": local(discharged) if gone else None,
                "discharged_at": discharged if gone else None,
                "planned_discharge_date": planned,
                "admission_mode": mode,
                "care_level": rng.choices([1, 2, 3, 4], CARE_LEVEL_WEIGHTS[ward.spec.code])[0]
                if ward.spec.code in CARE_LEVEL_WEIGHTS
                else None,
                "source": "hl7",
                "created_at": admitted,
                "updated_at": discharged if gone else admitted,
            }
        )

    def patient(elderly: bool | None = None) -> tuple[str, int]:
        sex = rng.choice("FM")
        if elderly is None:
            elderly = rng.random() < 0.2
        if elderly:
            return sex, rng.randint(75, 99)
        return sex, rng.randint(0, 17) if rng.random() < 0.25 else rng.randint(18, 74)

    # Warm start: wards about 85 % full on the first day of the history.
    for ward in wards.values():
        for _ in range(int(ward.capacity(HISTORY_DAYS) * 0.85)):
            admitted = midnight(start) - timedelta(days=rng.uniform(0, ward.spec.los[0]))
            sex, age = patient(ward.spec.code in ELDERLY_UNITS)
            mode = "mutation" if ward.spec.code in SMR_CODES else "urgences"
            add_stay(ward, admitted, mode, token(), token(), sex, max(age, 18))

    # Requests for a bed, processed in time order: (at, kind, payload).
    requests: list[tuple[datetime, int, dict[str, Any]]] = []
    for offset in range(HISTORY_DAYS, -1, -1):
        day = today - timedelta(days=offset)
        base = midnight(day)
        season = _season(day)
        for _ in range(_poisson(rng, ED_DAILY_MEAN * WEEKDAY[day.weekday()] * season)):
            arrived = base + timedelta(hours=rng.choices(range(24), HOURLY)[0] + rng.random())
            if arrived > now:
                continue
            sex, age = patient()
            p_admit = 0.05 if age < 18 else 0.1 if age < 40 else 0.24 if age < 75 else 0.4
            visit: dict[str, Any] = {
                "group_id": group.id,
                "site_id": sites[MCO_SITE].id,
                "encounter_ref": token(),
                "patient_ref": token(),
                "arrived_at": arrived,
                "admit_decision_at": None,
                "left_at": None,
                "outcome": None,
                "target_pool_id": None,
                "source": "hl7",
            }
            visits.append(visit)
            if rng.random() < p_admit * (1 + 0.8 * (season - 1)):
                decision = arrived + timedelta(hours=rng.lognormvariate(math.log(3.0), 0.5))
                if decision > now:
                    continue
                visit["admit_decision_at"] = decision
                if age < 18 or rng.random() < 0.12:  # no paediatrics here, or a specialty
                    left = decision + timedelta(hours=rng.lognormvariate(math.log(2.0), 0.5))
                    if left <= now:
                        visit.update(left_at=left, outcome="transfert")
                    continue
                targets = ED_TARGETS_ELDERLY if age >= 75 else ED_TARGETS_ADULT
                code = rng.choices(list(targets), list(targets.values()))[0]
                requests.append(
                    (decision, 0, {"visit": visit, "code": code, "sex": sex, "age": age})
                )
            else:
                left = arrived + timedelta(hours=rng.lognormvariate(math.log(3.2), 0.6))
                if left <= now:
                    outcome = rng.choices(
                        ["sortie", "fugue", "transfert", "deces"], [93, 4, 2.6, 0.4]
                    )
                    visit.update(left_at=left, outcome=outcome[0])
        for ward in wards.values():
            spec = ward.spec
            if not spec.planned_per_weekday or day.weekday() >= 5:
                continue
            for _ in range(_poisson(rng, spec.planned_per_weekday * 7 / 5)):
                if rng.random() < spec.mutation_share:
                    mode = "mutation"
                else:
                    mode = "transfert" if spec.code in SMR_CODES else "programme"
                hour = rng.uniform(7.5, 9.5) if mode == "programme" else rng.uniform(14, 17)
                requests.append(
                    (base + timedelta(hours=hour), 1, {"code": spec.code, "mode": mode})
                )

    requests.sort(key=lambda r: (r[0], r[1]))
    for at, kind, payload in requests:
        ward = wards[payload["code"]]
        days_before = (today - local(at)).days
        if kind == 0:
            visit = payload["visit"]
            got = ward.take_bed(at, days_before, MAX_BOARDING)
            if got is None:  # no bed in sight: sent to another hospital
                left = at + timedelta(hours=rng.uniform(4, 20))
                if left <= now:
                    visit.update(left_at=left, outcome="transfert")
                continue
            got += timedelta(minutes=rng.uniform(15, 60))
            visit["target_pool_id"] = ward.pool.id
            if got <= now:
                visit.update(left_at=got, outcome="hospitalise")
                add_stay(
                    ward,
                    got,
                    "urgences",
                    visit["encounter_ref"],
                    visit["patient_ref"],
                    payload["sex"],
                    payload["age"],
                )
            else:  # still waiting in the emergency department: the bed is promised
                heapq.heappush(ward.occupants, discharge_after(got, ward.spec))
            continue
        got = ward.take_bed(at, days_before, timedelta(0))
        if got is None:  # no bed: programmed admission postponed, transfer refused
            continue
        sex, age = patient(ward.spec.code in ELDERLY_UNITS or None)
        add_stay(ward, got, payload["mode"], token(), token(), sex, max(age, 18))

    session.execute(insert(EdVisit), visits)
    present = [s for s in stays if s["discharged_at"] is None]
    session.execute(insert(Stay), [s for s in stays if s["discharged_at"] is not None])
    present_stays = [Stay(**s) for s in present]
    session.add_all(present_stays)
    session.flush()
    for ward in wards.values():
        _add_beds(
            session,
            group,
            ward,
            [s for s in present_stays if s.mention == ward.spec.code],
            now,
            rng,
        )
    _add_staffing(session, group, wards, now)
    for login, full_name, role in STAFF:
        session.add(
            User(
                group_id=group.id,
                email=f"{login}@{EMAIL_DOMAIN}",
                full_name=full_name,
                password_hash=hash_password(password, password_iterations),
                role=role,
                created_at=now,
            )
        )
    session.commit()
    return group


def _add_capacity_history(
    session: Session, group: Group, ward: Ward, today: date, now: datetime
) -> None:
    spec = ward.spec
    if not spec.installed:
        return
    changes = [(HISTORY_DAYS, "ouverture", "Capacité initiale (démo)")]
    for start, end, _, reason in spec.closures:
        changes.append((start, reason, "Fermeture (démo)"))
        if end is not None:
            changes.append((end, "ouverture", "Réouverture (démo)"))
    for days_before, reason, comment in changes:
        session.add(
            CapacityChange(
                group_id=group.id,
                site_id=ward.pool.site_id,
                mention=spec.code,
                effective_date=today - timedelta(days=days_before),
                beds_installed=spec.installed,
                beds_open=ward.capacity(days_before),
                reason=reason,
                comment=comment,
                created_at=now,
            )
        )


def _add_beds(
    session: Session,
    group: Group,
    ward: Ward,
    present: list[Stay],
    now: datetime,
    rng: random.Random,
) -> None:
    """Single and double rooms; present stays get a bed; closed beds are blocked."""
    spec, pool = ward.spec, ward.pool
    if not spec.installed:
        return
    singles = round(spec.installed * spec.single_share)
    singles += (spec.installed - singles) % 2
    pool.isolation_rooms = 4 if spec.code == "reanimation" else max(1, spec.installed // 10)
    beds: list[Bed] = []

    def bed(room: str, label: str, isolation: bool) -> Bed:
        return Bed(
            group_id=group.id,
            site_id=pool.site_id,
            pool_id=pool.id,
            room=room,
            label=label,
            sex_constraint="X",
            isolation=isolation,
            status="libre",
            active=True,
            updated_at=now,
        )

    floor = spec.uf_code[:2]
    for n in range(1, singles + 1):
        room = f"{floor}{n:02d}"
        beds.append(bed(room, room, n <= pool.isolation_rooms))
    for n in range(singles + 1, singles + 1 + (spec.installed - singles) // 2):
        room = f"{floor}{n:02d}"
        beds.extend(bed(room, f"{room}{side}", False) for side in "AB")

    free = beds[:]
    rng.shuffle(free)
    for stay in present:
        place = free.pop()
        place.status, place.stay_id = "occupe", stay.id
    by_room: dict[str, list[Bed]] = {}
    for b in beds:
        by_room.setdefault(b.room, []).append(b)
    sex_of = {s.id: s.patient_sex for s in present}
    for room_beds in by_room.values():
        if len(room_beds) < 2:
            continue
        sexes = {sex_of[b.stay_id] for b in room_beds if b.stay_id is not None}
        occupied = sum(b.stay_id is not None for b in room_beds)
        if len(sexes) == 1 and rng.random() < (0.5 if occupied == 2 else 0.2):
            constraint = sexes.pop() or "X"
        elif not sexes and rng.random() < 0.1:
            constraint = rng.choice("FM")
        else:
            continue
        for b in room_beds:
            b.sex_constraint = constraint

    closed = spec.installed - pool.beds_open
    reasons = [r for start, end, _, r in spec.closures if end is None]
    for b in free[:closed]:
        b.status = "bloque"
        b.status_reason = f"Fermeture : {CAPACITY_REASONS[reasons[-1]].lower()}"
    rest = free[closed:]
    for b in rest:
        if rng.random() < 0.25:  # discharged this morning, not cleaned yet
            b.status = "a_nettoyer"
    if rest and spec.code == "medecine_polyvalente":
        rest[0].status, rest[0].status_reason = "bloque", "Lit médicalisé en panne"
    if rest and spec.code == "chirurgie_orthopedique":
        rest[0].status, rest[0].status_reason = "reserve", "Entrée programmée"
    session.add_all(beds)
    session.flush()
    stays = {s.id: s for s in present}
    for b in beds:
        if b.stay_id is not None:
            stays[b.stay_id].bed_id = b.id


def _add_staffing(session: Session, group: Group, wards: dict[str, Ward], now: datetime) -> None:
    """Weekly care hours per unit, thinner at weekends, as in the SMR demo."""
    for code, ward in wards.items():
        if not ward.spec.installed:
            continue
        if code in CARE_LEVEL_WEIGHTS:
            weights = CARE_LEVEL_WEIGHTS[code]
            minutes = sum(w * c for w, c in zip(weights, (45, 90, 150, 240), strict=True)) / 100
        else:
            minutes = 360.0 if code == "reanimation" else 150.0
        base = ward.pool.beds_open * minutes / 60
        for weekday in range(7):
            session.add(
                StaffPlan(
                    group_id=group.id,
                    site_id=ward.pool.site_id,
                    mention=code,
                    weekday=weekday,
                    care_hours=round(base * (0.98 if weekday >= 5 else 1.12), 1),
                    updated_at=now,
                )
            )
