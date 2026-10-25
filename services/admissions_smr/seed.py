"""Synthetic demo group, for demos and onboarding rehearsals only.

The data is stationary on purpose: it contains NO simulated effect of the
product. The North Star computed on it should usually show an interval that
crosses zero. Over many seeds, intervals exclude zero at the rates measured in
``domain/metrics.py`` (fee falsely due in about 2-7 % of replicates). The
default seed is one whose result is the typical null; other seeds are useful
to rehearse how to present a spurious signal.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from services.admissions_smr.models import (
    AdmissionRequest,
    BedPool,
    CapacityChange,
    Group,
    RequestEvent,
    Site,
    Stay,
    User,
)
from services.admissions_smr.security import hash_password

HISTORY_DAYS = 900

# Mean length of stay (days) and gamma shape per mention, for the simulation only.
LOS = {
    "polyvalent": (24.0, 2.2),
    "geriatrie": (31.0, 2.0),
    "locomoteur": (21.0, 2.6),
    "neuro": (44.0, 1.8),
    "cardio": (20.0, 3.0),
    "pneumo": (23.0, 2.4),
}

REFERRERS = [
    ("CH des Monts d'Or", "Médecine polyvalente"),
    ("Hôpital Saint-Rambert", "Orthopédie"),
    ("Clinique des Brotteaux", "Chirurgie orthopédique"),
    ("CH de la Dombes", "Court séjour gériatrique"),
    ("Hôpital Croix-Pâquet", "Neurologie — UNV"),
    ("Clinique Bellecour Sud", "Cardiologie"),
    ("CH du Beaujolais", "Pneumologie"),
    ("Hôpital Fourvière", "Urgences — UHCD"),
]

CATEGORIES = {
    "polyvalent": ["Suites de chirurgie digestive", "Décompensation cardiaque", "Pneumopathie"],
    "geriatrie": ["Fracture du col fémoral opérée", "Chutes à répétition", "Syndrome confusionnel"],
    "locomoteur": ["Prothèse totale de genou", "Prothèse totale de hanche", "Rachis opéré"],
    "neuro": ["AVC ischémique", "Traumatisme crânien", "Sclérose en plaques — poussée"],
    "cardio": ["Post-infarctus", "Chirurgie valvulaire", "Insuffisance cardiaque"],
    "pneumo": ["BPCO exacerbée", "Post-COVID long", "Réhabilitation pré-greffe"],
}


@dataclass(frozen=True)
class PoolSpec:
    mention: str
    installed: int
    closures: tuple[tuple[int, int, str], ...] = ()  # (days before today, beds closed, reason)


SITES: list[tuple[str, str, str, str, list[PoolSpec]]] = [
    (
        "SMR Les Tilleuls",
        "690000011",
        "Lyon",
        "oxygene,nutrition_enterale",
        [
            PoolSpec("polyvalent", 30),
            PoolSpec("geriatrie", 40, ((120, 4, "personnel"),)),
            PoolSpec("locomoteur", 20),
        ],
    ),
    (
        "Clinique du Parc",
        "690000029",
        "Villeurbanne",
        "oxygene,tracheotomie,ventilation",
        [
            PoolSpec("locomoteur", 35),
            PoolSpec("neuro", 25, ((60, 3, "travaux"),)),
        ],
    ),
    (
        "SMR Val de Saône",
        "710000037",
        "Mâcon",
        "oxygene,bariatrique",
        [
            PoolSpec("polyvalent", 25),
            PoolSpec("geriatrie", 30, ((200, 4, "personnel"),)),
            PoolSpec("cardio", 20),
        ],
    ),
    (
        "SMR Côte Bleue",
        "010000045",
        "Bourg-en-Bresse",
        "oxygene,ventilation",
        [
            PoolSpec("pneumo", 25),
            PoolSpec("cardio", 15),
        ],
    ),
]

DEMO_USERS = [
    ("admin@demo.hospitalos.fr", "Camille Admin", "admin_groupe", None),
    ("coordination@demo.hospitalos.fr", "Inès Coordination", "coordination", None),
    ("tilleuls@demo.hospitalos.fr", "Paul — Les Tilleuls", "coordination", "SMR Les Tilleuls"),
    ("direction@demo.hospitalos.fr", "Hélène Direction", "direction", None),
    ("agent@demo.hospitalos.fr", "Agent d'ingestion", "ingestion", None),
]


def _open_beds(spec: PoolSpec, days_before: int) -> tuple[int, str]:
    closed, reason = 0, "ouverture"
    for start, beds, why in spec.closures:
        if days_before <= start:
            closed += beds
            reason = why
    return spec.installed - closed, reason


def _at(zone: ZoneInfo, day: date, hour: float) -> datetime:
    h = int(hour)
    m = int((hour - h) * 60)
    return datetime.combine(day, time(h % 24, m), tzinfo=zone).astimezone(UTC)


def seed_demo(
    session: Session,
    today: date,
    password: str,
    password_iterations: int,
    timezone: str = "Europe/Paris",
    seed: int = 2,
) -> Group:
    rng = random.Random(seed)
    zone = ZoneInfo(timezone)
    now = datetime.now(UTC)
    group = Group(
        name="Groupe Démo Réadaptation",
        baseline_start=today - timedelta(days=240),
        baseline_end=today - timedelta(days=121),
        value_per_bed_day=150.0,
        success_fee_rate=0.15,
        created_at=now,
    )
    session.add(group)
    session.flush()

    sites: dict[str, Site] = {}
    for name, finess, city, caps, pools in SITES:
        site = Site(
            group_id=group.id,
            name=name,
            finess=finess,
            city=city,
            capabilities=caps,
            created_at=now,
        )
        session.add(site)
        session.flush()
        sites[name] = site
        for spec in pools:
            beds_open, _ = _open_beds(spec, 0)
            site.pools.append(
                BedPool(
                    site_id=site.id,
                    mention=spec.mention,
                    beds_installed=spec.installed,
                    beds_open=beds_open,
                    isolation_rooms=max(1, spec.installed // 10),
                    updated_at=now,
                )
            )
            session.add(
                CapacityChange(
                    group_id=group.id,
                    site_id=site.id,
                    mention=spec.mention,
                    effective_date=today - timedelta(days=HISTORY_DAYS),
                    beds_installed=spec.installed,
                    beds_open=spec.installed,
                    reason="ouverture",
                    comment="Capacité initiale (démo)",
                    created_at=now,
                )
            )
            for start, beds, why in spec.closures:
                session.add(
                    CapacityChange(
                        group_id=group.id,
                        site_id=site.id,
                        mention=spec.mention,
                        effective_date=today - timedelta(days=start),
                        beds_installed=spec.installed,
                        beds_open=spec.installed - beds,
                        reason=why,
                        comment="Fermeture (démo)",
                        created_at=now,
                    )
                )

    users: dict[str, User] = {}
    for email, full_name, role, site_name in DEMO_USERS:
        user = User(
            group_id=group.id,
            email=email,
            full_name=full_name,
            password_hash=hash_password(password, password_iterations),
            role=role,
            site_id=sites[site_name].id if site_name else None,
            created_at=now,
        )
        session.add(user)
        users[email] = user
    session.flush()
    coordinator = users["coordination@demo.hospitalos.fr"]

    patient_counter = 0

    def next_patient() -> str:
        nonlocal patient_counter
        patient_counter += 1
        return f"PAT-{patient_counter:06d}"

    request_window = 90
    for site_name, _, _, _, pools in SITES:
        site = sites[site_name]
        for spec in pools:
            mean_los, shape = LOS[spec.mention]
            discharges: list[date] = []
            # Warm start: fill the pool at the beginning of the history.
            start_day = today - timedelta(days=HISTORY_DAYS)
            for _ in range(int(spec.installed * 0.9)):
                elapsed = rng.randint(0, int(mean_los))
                los = max(1, round(rng.gammavariate(shape, mean_los / shape)))
                admit = start_day - timedelta(days=elapsed)
                discharge = admit + timedelta(days=max(los, elapsed + 1))
                discharges.append(discharge)
                _add_stay(
                    session, group, site, spec.mention, next_patient(), admit, discharge, today, rng
                )
            for offset in range(HISTORY_DAYS, -1, -1):
                day = today - timedelta(days=offset)
                beds_open, _ = _open_beds(spec, offset)
                discharges = [d for d in discharges if d > day]
                weekday = day.weekday()
                rate = beds_open * 0.97 / mean_los * (0.35 if weekday >= 5 else 1.25)
                arrivals = _poisson(rng, rate)
                for _ in range(arrivals):
                    if len(discharges) >= beds_open:
                        break
                    los = max(2, round(rng.gammavariate(shape, mean_los / shape)))
                    discharge = day + timedelta(days=los)
                    if discharge.weekday() >= 5 and rng.random() < 0.75:
                        discharge += timedelta(days=7 - discharge.weekday())
                    discharges.append(discharge)
                    patient = next_patient()
                    stay = _add_stay(
                        session, group, site, spec.mention, patient, day, discharge, today, rng
                    )
                    if offset <= request_window and offset > 0 and rng.random() < 0.8:
                        _add_handled_request(
                            session,
                            group,
                            site,
                            spec.mention,
                            patient,
                            day,
                            stay,
                            zone,
                            rng,
                            coordinator.id,
                        )
            # Requests that did not end in an admission (refused or lost).
            for offset in range(request_window, 0, -1):
                day = today - timedelta(days=offset)
                if day.weekday() < 5 and rng.random() < spec.installed / 60:
                    _add_closed_request(
                        session,
                        group,
                        site,
                        spec.mention,
                        next_patient(),
                        day,
                        zone,
                        rng,
                        coordinator.id,
                    )

    _add_open_requests(session, group, sites, today, zone, rng, coordinator.id, next_patient)
    session.commit()
    return group


def _poisson(rng: random.Random, lam: float) -> int:
    # Knuth; lam is small (a few arrivals per day).
    limit = pow(2.718281828459045, -lam)
    k, p = 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _add_stay(
    session: Session,
    group: Group,
    site: Site,
    mention: str,
    patient: str,
    admit: date,
    discharge: date,
    today: date,
    rng: random.Random,
) -> Stay:
    known = discharge <= today
    planned: date | None = None
    if not known and (discharge - today).days <= 21 and rng.random() < 0.55:
        planned = discharge + timedelta(days=rng.choice([0, 0, 0, 0, 1, 2, -1]))
        planned = max(planned, today)
    stay = Stay(
        group_id=group.id,
        site_id=site.id,
        mention=mention,
        patient_ref=patient,
        admission_date=admit,
        discharge_date=discharge if known else None,
        planned_discharge_date=planned,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(stay)
    return stay


def _referrer_for(mention: str, rng: random.Random) -> tuple[str, str]:
    preferred = {
        "geriatrie": [0, 3, 7],
        "locomoteur": [1, 2],
        "neuro": [4],
        "cardio": [5],
        "pneumo": [6],
        "polyvalent": [0, 7, 3],
    }[mention]
    if rng.random() < 0.75:
        return REFERRERS[rng.choice(preferred)]
    return rng.choice(REFERRERS)


def _base_request(
    group: Group,
    site: Site | None,
    mention: str,
    patient: str,
    received: datetime,
    desired: date | None,
    rng: random.Random,
) -> AdmissionRequest:
    facility, unit = _referrer_for(mention, rng)
    needs = []
    if rng.random() < 0.15:
        needs.append("oxygene")
    if mention == "neuro" and rng.random() < 0.1:
        needs.append("tracheotomie")
    return AdmissionRequest(
        group_id=group.id,
        source=rng.choices(["viatrajectoire", "mail", "fax", "telephone"], [70, 15, 10, 5])[0],
        external_ref=f"VT-{received:%Y%m%d}-{patient[-6:]}",
        received_at=received,
        referrer_facility=facility,
        referrer_unit=unit,
        patient_ref=patient,
        patient_age=rng.randint(68, 94) if mention == "geriatrie" else rng.randint(35, 88),
        patient_sex=rng.choice(["F", "M"]),
        mention_requested=mention,
        clinical_category=rng.choice(CATEGORIES[mention]),
        care_level=rng.choices([1, 2, 3, 4], [15, 40, 30, 15])[0],
        isolation_required=rng.random() < 0.07,
        special_needs=",".join(needs),
        desired_date=desired,
        site_id=site.id if site else None,
        created_at=received,
        updated_at=received,
    )


def _add_handled_request(
    session: Session,
    group: Group,
    site: Site,
    mention: str,
    patient: str,
    admit_day: date,
    stay: Stay,
    zone: ZoneInfo,
    rng: random.Random,
    actor: int,
) -> None:
    received_day = admit_day - timedelta(days=rng.randint(1, 6))
    received = _at(zone, received_day, rng.uniform(8, 18))
    response = received + timedelta(hours=rng.lognormvariate(2.9, 0.7))
    req = _base_request(group, site, mention, patient, received, admit_day, rng)
    req.status = "admise"
    req.proposed_date = admit_day
    req.first_response_at = response
    req.closed_at = _at(zone, admit_day, 14)
    req.events.extend(
        [
            RequestEvent(
                at=received, kind="recue", to_status="nouvelle", detail=f"Source : {req.source}"
            ),
            RequestEvent(
                at=response,
                actor_user_id=actor,
                kind="accord",
                from_status="nouvelle",
                to_status="accord",
                detail=f"Entrée proposée le {admit_day:%d/%m/%Y}",
            ),
            RequestEvent(
                at=response + timedelta(hours=rng.uniform(2, 30)),
                actor_user_id=actor,
                kind="confirmation",
                from_status="accord",
                to_status="confirmee",
            ),
            RequestEvent(
                at=req.closed_at,
                actor_user_id=actor,
                kind="admission",
                from_status="confirmee",
                to_status="admise",
            ),
        ]
    )
    session.add(req)
    session.flush()
    stay.request_id = req.id


def _add_closed_request(
    session: Session,
    group: Group,
    site: Site,
    mention: str,
    patient: str,
    day: date,
    zone: ZoneInfo,
    rng: random.Random,
    actor: int,
) -> None:
    received = _at(zone, day, rng.uniform(8, 18))
    response = received + timedelta(hours=rng.lognormvariate(3.0, 0.8))
    req = _base_request(
        group, site, mention, patient, received, day + timedelta(days=rng.randint(1, 7)), rng
    )
    req.events.append(RequestEvent(at=received, kind="recue", to_status="nouvelle"))
    if rng.random() < 0.6:
        req.status = "refusee"
        req.refusal_reason = rng.choices(
            [
                "pas_de_lit",
                "charge_en_soins",
                "projet_inadapte",
                "besoin_technique",
                "dossier_incomplet",
            ],
            [45, 20, 15, 10, 10],
        )[0]
        req.first_response_at = response
        req.closed_at = response
        req.events.append(
            RequestEvent(
                at=response,
                actor_user_id=actor,
                kind="refus",
                from_status="nouvelle",
                to_status="refusee",
            )
        )
    else:
        req.status = "perdue"
        req.loss_reason = rng.choices(
            ["autre_etablissement", "retour_domicile", "etat_clinique", "annulation_adresseur"],
            [55, 20, 15, 10],
        )[0]
        lost_at = response + timedelta(hours=rng.uniform(4, 72))
        if rng.random() < 0.5:
            req.first_response_at = response
            req.proposed_date = day + timedelta(days=rng.randint(2, 8))
            req.events.append(
                RequestEvent(
                    at=response,
                    actor_user_id=actor,
                    kind="accord",
                    from_status="nouvelle",
                    to_status="accord",
                )
            )
            prev = "accord"
        else:
            prev = "nouvelle"
        req.closed_at = lost_at
        req.events.append(
            RequestEvent(
                at=lost_at, actor_user_id=actor, kind="perte", from_status=prev, to_status="perdue"
            )
        )
    session.add(req)


def _add_open_requests(
    session: Session,
    group: Group,
    sites: dict[str, Site],
    today: date,
    zone: ZoneInfo,
    rng: random.Random,
    actor: int,
    next_patient: Callable[[], str],
) -> None:
    now = datetime.now(UTC)
    plan = [
        ("nouvelle", None, 12),
        ("en_etude", "site", 4),
        ("accord", "site", 4),
        ("confirmee", "site", 2),
    ]
    site_list = list(sites.values())
    for status, assign, count in plan:
        for _ in range(count):
            site = rng.choice(site_list)
            mention = rng.choice([p.mention for p in site.pools])
            hours_ago = (
                rng.uniform(0.5, 70) if status in ("nouvelle", "en_etude") else rng.uniform(20, 120)
            )
            received = now - timedelta(hours=hours_ago)
            desired = today + timedelta(days=rng.choice([0, 1, 2, 3, 5, 7, 10]))
            req = _base_request(
                group, site if assign else None, mention, next_patient(), received, desired, rng
            )
            req.events.append(
                RequestEvent(
                    at=received, kind="recue", to_status="nouvelle", detail=f"Source : {req.source}"
                )
            )
            if status == "nouvelle" and rng.random() < 0.3:
                req.site_id = site.id
            if status != "nouvelle":
                step = received + timedelta(hours=min(hours_ago * 0.4, rng.uniform(1, 12)))
                req.events.append(
                    RequestEvent(
                        at=step,
                        actor_user_id=actor,
                        kind="etude",
                        from_status="nouvelle",
                        to_status="en_etude",
                    )
                )
            if status in ("accord", "confirmee"):
                answered = received + timedelta(hours=min(hours_ago * 0.7, rng.uniform(6, 30)))
                req.first_response_at = answered
                req.proposed_date = today + timedelta(days=rng.randint(1, 6))
                req.events.append(
                    RequestEvent(
                        at=answered,
                        actor_user_id=actor,
                        kind="accord",
                        from_status="en_etude",
                        to_status="accord",
                        detail=f"Entrée proposée le {req.proposed_date:%d/%m/%Y}",
                    )
                )
            if status == "confirmee":
                req.events.append(
                    RequestEvent(
                        at=received + timedelta(hours=hours_ago * 0.9),
                        actor_user_id=actor,
                        kind="confirmation",
                        from_status="accord",
                        to_status="confirmee",
                    )
                )
            req.status = status
            session.add(req)
