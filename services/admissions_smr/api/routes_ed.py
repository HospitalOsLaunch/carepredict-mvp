"""Emergency department census, boarding at 10:00, HET / Plan blanc (owner: beds-ed).

Roles: every read role sees the census, the series and the tension status within its site
scope. A manual census declaration (fallback when there is no feed) and the HET / Plan
blanc declarations are recorded by ``coordination`` (bed management cell) or
``admin_groupe``: the ``direction`` role is read-only in this product, so the decision taken
by the management is entered by one of them, with the name of who recorded it. A
coordinator restricted to one site declares for that site only, never establishment-wide.
The product only suggests (HET decision aid); it never declares.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, time, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import or_, select

from services.admissions_smr.api.deps import UNPROCESSABLE, Ctx, ReadCtx, WriteCtx
from services.admissions_smr.api.routes_beds import availability_out, unit_label, unit_views
from services.admissions_smr.clock import local_time
from services.admissions_smr.domain.ed import (
    BOARDING_ARRIVED_BEFORE,
    BOARDING_HOUR,
    STALE_AFTER,
    AdmittedStay,
    Declared,
    Visit,
    boarding_10h,
    census,
    daily_series,
    hosted_elsewhere,
)
from services.admissions_smr.domain.tension import (
    AID_LEVELS,
    DECLARATION_LEVELS,
    HetInputs,
    het_aid,
)
from services.admissions_smr.models import (
    BedPool,
    EdSnapshot,
    EdVisit,
    Site,
    Stay,
    TensionDeclaration,
    User,
)
from services.admissions_smr.schemas_liscop import (
    Boarding10hOut,
    BoardingDayOut,
    BoardingSeriesOut,
    CensusNowOut,
    CriterionOut,
    EdCensusOut,
    EdSiteOut,
    EdSnapshotIn,
    EdSnapshotOut,
    HetAidOut,
    TensionDeclarationIn,
    TensionDeclarationOut,
    TensionDeclarationPatch,
    TensionStatusOut,
    UnitTensionOut,
)
from services.admissions_smr.service import get_site, group_sites

router = APIRouter(tags=["urgences"])

CLOCK_SKEW = timedelta(minutes=5)
DECLARATION_MAX_AGE = timedelta(days=31)
NON_MCO = frozenset({"smr", "urgences", "medico_social"})

DEFINITIONS = [
    "Présents : arrivés et pas encore sortis (au plus 72 h après l'arrivée ; au-delà, un "
    "message de sortie perdu est supposé).",
    "En attente de lit : présents avec une décision d'hospitalisation.",
    f"Lits brancards à {BOARDING_HOUR:%H} h : présents à {BOARDING_HOUR:%H}:00 (heure de "
    f"Paris) avec une décision d'hospitalisation, arrivés avant {BOARDING_ARRIVED_BEFORE:%H}:00 "
    "le jour même ou la veille, donc ayant passé la nuit ou le petit matin sur un brancard. "
    "Définition HospitalOS, à valider avec l'ARS.",
    "Hébergés : patients hospitalisés depuis les urgences, encore présents, dans une unité "
    "d'une autre discipline que l'unité visée par les urgences.",
    "Une déclaration manuelle du jour remplace le calcul pour ce jour ; le calcul reste "
    "affiché à côté.",
]

AID_NOTICE = (
    "Aide à la décision : la déclaration reste une décision de la direction. Seuils par "
    "défaut, à calibrer avec la direction et l'ARS."
)


# --- loading ------------------------------------------------------------------------------


def ed_sites(ctx: Ctx) -> list[Site]:
    return [s for s in group_sites(ctx) if any(p.unit_type == "urgences" for p in s.pools)]


def ed_site(ctx: Ctx, site_id: int | None) -> Site:
    if site_id is None:
        sites = ed_sites(ctx)
        if not sites:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucun service d'urgences visible")
        return sites[0]
    site = get_site(ctx, site_id)
    if not ctx.can_see_site(site.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Site hors de votre périmètre")
    return site


def load_visits(ctx: Ctx, site_id: int, since: datetime) -> list[Visit]:
    rows = ctx.session.execute(
        select(EdVisit.arrived_at, EdVisit.admit_decision_at, EdVisit.left_at).where(
            EdVisit.group_id == ctx.group.id,
            EdVisit.site_id == site_id,
            EdVisit.arrived_at >= since,
            EdVisit.arrived_at <= ctx.clock.now(),
        )
    )
    return [Visit(a, d, left) for a, d, left in rows]


def load_admitted(ctx: Ctx, site_id: int, since: datetime) -> list[AdmittedStay]:
    pools = ctx.session.execute(
        select(BedPool.id, BedPool.site_id, BedPool.mention, BedPool.discipline)
        .join(Site, Site.id == BedPool.site_id)
        .where(Site.group_id == ctx.group.id)
    ).all()
    by_id = {p.id: p.discipline for p in pools}
    by_code = {(p.site_id, p.mention): p.discipline for p in pools}
    rows = ctx.session.execute(
        select(
            Stay.admitted_at, Stay.discharged_at, Stay.site_id, Stay.mention, EdVisit.target_pool_id
        )
        .join(
            EdVisit,
            (EdVisit.group_id == Stay.group_id) & (EdVisit.encounter_ref == Stay.encounter_ref),
        )
        .where(
            Stay.group_id == ctx.group.id,
            EdVisit.site_id == site_id,
            Stay.admitted_at.is_not(None),
            Stay.admitted_at <= ctx.clock.now(),
            or_(Stay.discharged_at.is_(None), Stay.discharged_at >= since),
        )
    )
    return [
        AdmittedStay(
            admitted_at=admitted,
            discharged_at=discharged,
            discipline=by_code.get((stay_site, mention), "inconnue"),
            target_discipline=by_id.get(target) if target is not None else None,
        )
        for admitted, discharged, stay_site, mention, target in rows
        if admitted is not None
    ]


def declarations_since(ctx: Ctx, site_id: int, since: datetime) -> list[EdSnapshot]:
    return list(
        ctx.session.scalars(
            select(EdSnapshot)
            .where(
                EdSnapshot.group_id == ctx.group.id,
                EdSnapshot.site_id == site_id,
                EdSnapshot.source == "declaration",
                EdSnapshot.at >= since,
            )
            .order_by(EdSnapshot.at.desc(), EdSnapshot.id.desc())
        )
    )


def as_declared(rows: Sequence[EdSnapshot]) -> list[Declared]:
    return [Declared(r.at, r.present, r.waiting_bed, r.boarding, r.hosted_elsewhere) for r in rows]


def snapshot_out(s: EdSnapshot) -> EdSnapshotOut:
    return EdSnapshotOut(
        id=s.id,
        site_id=s.site_id,
        at=s.at,
        present=s.present,
        waiting_bed=s.waiting_bed,
        boarding=s.boarding,
        hosted_elsewhere=s.hosted_elsewhere,
        source=s.source,
        comment=s.comment,
    )


# --- census -------------------------------------------------------------------------------


def boarding_today(ctx: Ctx, site: Site, visits: Sequence[Visit]) -> Boarding10hOut:
    zone, now, today = ctx.clock.zone, ctx.clock.now(), ctx.clock.today()
    t10 = local_time(today, BOARDING_HOUR, zone)
    reached = now >= t10
    computed = boarding_10h(visits, today, zone, as_of=None if reached else now)
    declared = next(
        (
            d
            for d in declarations_since(ctx, site.id, local_time(today, time(0), zone))
            if d.at.astimezone(zone).date() == today
        ),
        None,
    )
    return Boarding10hOut(
        day=today,
        at=t10,
        reached=reached,
        boarding=declared.boarding if declared else computed,
        computed_boarding=computed,
        source="declaration" if declared else "calcul",
    )


@router.get("/ed/census", response_model=EdCensusOut)
def ed_census(ctx: ReadCtx, site_id: int | None = None) -> EdCensusOut:
    site = ed_site(ctx, site_id)
    now = ctx.clock.now()
    since = now - STALE_AFTER - timedelta(days=1)
    visits = load_visits(ctx, site.id, since)
    c = census(visits, now)
    latest = ctx.session.scalars(
        select(EdSnapshot)
        .where(
            EdSnapshot.group_id == ctx.group.id,
            EdSnapshot.site_id == site.id,
            EdSnapshot.source == "declaration",
        )
        .order_by(EdSnapshot.at.desc(), EdSnapshot.id.desc())
        .limit(1)
    ).first()
    return EdCensusOut(
        site_id=site.id,
        site_name=site.name,
        ed_sites=[EdSiteOut(id=s.id, name=s.name) for s in ed_sites(ctx)],
        now=CensusNowOut(
            at=now,
            present=c.present,
            waiting_bed=c.waiting_bed,
            longest_wait_hours=c.longest_wait_hours,
            hosted_elsewhere=hosted_elsewhere(load_admitted(ctx, site.id, now), now),
        ),
        today_10h=boarding_today(ctx, site, visits),
        latest_declaration=snapshot_out(latest) if latest else None,
        definitions=DEFINITIONS,
    )


def series(ctx: Ctx, site: Site, days: int) -> list[BoardingDayOut]:
    zone, now, today = ctx.clock.zone, ctx.clock.now(), ctx.clock.today()
    last = today if now >= local_time(today, BOARDING_HOUR, zone) else today - timedelta(days=1)
    span = [last - timedelta(days=k) for k in range(days - 1, -1, -1)]
    since = local_time(span[0], BOARDING_HOUR, zone) - STALE_AFTER
    points = daily_series(
        load_visits(ctx, site.id, since),
        load_admitted(ctx, site.id, since),
        span,
        zone,
        as_declared(declarations_since(ctx, site.id, local_time(span[0], time(0), zone))),
    )
    return [
        BoardingDayOut(
            day=p.day,
            present=p.present,
            waiting_bed=p.waiting_bed,
            boarding=p.boarding,
            hosted_elsewhere=p.hosted_elsewhere,
            source=p.source,
            computed_boarding=p.computed_boarding,
        )
        for p in points
    ]


@router.get("/ed/boarding", response_model=BoardingSeriesOut)
def ed_boarding(
    ctx: ReadCtx, site_id: int | None = None, days: int = Query(90, ge=1, le=366)
) -> BoardingSeriesOut:
    site = ed_site(ctx, site_id)
    return BoardingSeriesOut(site_id=site.id, days=series(ctx, site, days))


@router.get("/ed/snapshots", response_model=list[EdSnapshotOut])
def list_snapshots(ctx: ReadCtx, site_id: int | None = None) -> list[EdSnapshotOut]:
    site = ed_site(ctx, site_id)
    rows = declarations_since(ctx, site.id, ctx.clock.now() - timedelta(days=90))
    return [snapshot_out(s) for s in rows[:50]]


@router.post("/ed/snapshots", response_model=EdSnapshotOut, status_code=201)
def declare_snapshot(body: EdSnapshotIn, ctx: WriteCtx) -> EdSnapshotOut:
    site = ed_site(ctx, body.site_id)
    now = ctx.clock.now()
    at = body.at or now
    if at.tzinfo is None:
        raise HTTPException(UNPROCESSABLE, "Indiquez le fuseau horaire de l'heure déclarée")
    if at > now + CLOCK_SKEW or at < now - DECLARATION_MAX_AGE:
        raise HTTPException(UNPROCESSABLE, "Heure hors de la fenêtre autorisée (31 derniers jours)")
    if body.waiting_bed > body.present or body.boarding > body.waiting_bed:
        raise HTTPException(
            UNPROCESSABLE, "Brancards ≤ en attente de lit ≤ présents : vérifiez les nombres"
        )
    snap = EdSnapshot(
        group_id=ctx.group.id,
        site_id=site.id,
        at=at,
        present=body.present,
        waiting_bed=body.waiting_bed,
        boarding=body.boarding,
        hosted_elsewhere=body.hosted_elsewhere,
        source="declaration",
        declared_by=ctx.user.id,
        comment=body.comment,
    )
    ctx.session.add(snap)
    ctx.session.flush()
    ctx.audit(
        "urgences.declaration",
        "ed_snapshot",
        snap.id,
        f"présents {body.present}, attente {body.waiting_bed}, brancards {body.boarding}",
    )
    ctx.session.commit()
    return snapshot_out(snap)


# --- tension ------------------------------------------------------------------------------


def declaration_out(d: TensionDeclaration, names: dict[int, str]) -> TensionDeclarationOut:
    return TensionDeclarationOut(
        id=d.id,
        site_id=d.site_id,
        kind=d.kind,
        level=d.level,
        started_at=d.started_at,
        ended_at=d.ended_at,
        declared_by=names.get(d.declared_by, "—"),
        comment=d.comment,
    )


def visible_declarations(ctx: Ctx, active_only: bool) -> list[TensionDeclarationOut]:
    query = select(TensionDeclaration).where(TensionDeclaration.group_id == ctx.group.id)
    if ctx.site_scope is not None:
        query = query.where(
            or_(
                TensionDeclaration.site_id.is_(None),
                TensionDeclaration.site_id == ctx.site_scope,
            )
        )
    if active_only:
        query = query.where(TensionDeclaration.ended_at.is_(None))
    rows = list(
        ctx.session.scalars(
            query.order_by(
                TensionDeclaration.started_at.desc(), TensionDeclaration.id.desc()
            ).limit(100)
        )
    )
    user_ids = {d.declared_by for d in rows}
    names = dict(
        ctx.session.execute(select(User.id, User.full_name).where(User.id.in_(user_ids))).all()
    )
    return [declaration_out(d, names) for d in rows]


def aid_for(ctx: Ctx, site: Site, mco: Sequence[UnitTensionOut]) -> HetAidOut:
    now = ctx.clock.now()
    visits = load_visits(ctx, site.id, now - STALE_AFTER - timedelta(days=2))
    c = census(visits, now)
    board = boarding_today(ctx, site, visits)
    # Before 10:00, the last known value is yesterday's.
    boarding = board.boarding if board.reached else series(ctx, site, 1)[0].boarding
    aid = het_aid(
        HetInputs(
            boarding_10h=boarding,
            waiting_bed=c.waiting_bed,
            longest_wait_hours=c.longest_wait_hours,
            critical_units=sum(u.tension.level == "critique" for u in mco),
            mco_units=len(mco),
        )
    )
    return HetAidOut(
        site_id=site.id,
        level=aid.level,
        label=AID_LEVELS[aid.level],
        criteria=[
            CriterionOut(
                code=k.code,
                label=k.label,
                value=k.value,
                threshold=k.threshold,
                triggered=k.triggered,
            )
            for k in aid.criteria
        ],
        notice=AID_NOTICE,
    )


@router.get("/tension/status", response_model=TensionStatusOut)
def tension_status(ctx: ReadCtx, site_id: int | None = None) -> TensionStatusOut:
    views = unit_views(ctx.session, ctx.group.id, group_sites(ctx))
    units = [
        UnitTensionOut(
            site_id=v.site.id,
            site_name=v.site.name,
            pool_id=v.pool.id,
            code=v.pool.mention,
            label=unit_label(v.pool),
            discipline=v.pool.discipline,
            installed=v.availability.installed,
            usable=v.availability.usable,
            tension=availability_out(v.availability).tension,
        )
        for v in views
    ]
    aid = None
    if site_id is not None or ed_sites(ctx):
        site = ed_site(ctx, site_id)
        mco = [
            u
            for u, v in zip(units, views, strict=True)
            if v.site.id == site.id and v.pool.unit_type not in NON_MCO
        ]
        aid = aid_for(ctx, site, mco)
    return TensionStatusOut(
        generated_at=ctx.clock.now(),
        units=units,
        aid=aid,
        active_declarations=visible_declarations(ctx, active_only=True),
    )


@router.get("/tension/declarations", response_model=list[TensionDeclarationOut])
def list_declarations(ctx: ReadCtx, active: bool = False) -> list[TensionDeclarationOut]:
    return visible_declarations(ctx, active_only=active)


def check_scope(ctx: Ctx, site_id: int | None) -> None:
    if site_id is None:
        if ctx.site_scope is not None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Déclaration pour l'établissement hors de votre périmètre",
            )
        return
    site = get_site(ctx, site_id)
    if not ctx.can_see_site(site.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Site hors de votre périmètre")


def check_level(kind: str, level: str) -> None:
    if level not in DECLARATION_LEVELS[kind]:
        raise HTTPException(UNPROCESSABLE, "Niveau inconnu pour ce type de déclaration")


def check_instant(ctx: Ctx, at: datetime, label: str) -> None:
    if at.tzinfo is None:
        raise HTTPException(UNPROCESSABLE, f"{label} : indiquez le fuseau horaire")
    if at > ctx.clock.now() + CLOCK_SKEW:
        raise HTTPException(UNPROCESSABLE, f"{label} dans le futur")


@router.post("/tension/declarations", response_model=TensionDeclarationOut, status_code=201)
def declare_tension(body: TensionDeclarationIn, ctx: WriteCtx) -> TensionDeclarationOut:
    check_scope(ctx, body.site_id)
    check_level(body.kind, body.level)
    started = body.started_at or ctx.clock.now()
    check_instant(ctx, started, "Début")
    active = ctx.session.scalar(
        select(TensionDeclaration.id).where(
            TensionDeclaration.group_id == ctx.group.id,
            TensionDeclaration.kind == body.kind,
            TensionDeclaration.ended_at.is_(None),
            TensionDeclaration.site_id.is_(None)
            if body.site_id is None
            else TensionDeclaration.site_id == body.site_id,
        )
    )
    if active is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Une déclaration de ce type est déjà en cours : clôturez-la"
        )
    decl = TensionDeclaration(
        group_id=ctx.group.id,
        site_id=body.site_id,
        kind=body.kind,
        level=body.level,
        started_at=started,
        declared_by=ctx.user.id,
        comment=body.comment,
    )
    ctx.session.add(decl)
    ctx.session.flush()
    ctx.audit("tension.declaration", "tension_declaration", decl.id, f"{body.kind} {body.level}")
    ctx.session.commit()
    return declaration_out(decl, {ctx.user.id: ctx.user.full_name})


@router.patch("/tension/declarations/{declaration_id}", response_model=TensionDeclarationOut)
def update_declaration(
    declaration_id: int, body: TensionDeclarationPatch, ctx: WriteCtx
) -> TensionDeclarationOut:
    decl = ctx.session.get(TensionDeclaration, declaration_id)
    if decl is None or decl.group_id != ctx.group.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Déclaration introuvable")
    check_scope(ctx, decl.site_id)
    if decl.ended_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Déclaration déjà clôturée")
    changes = body.model_dump(exclude_unset=True)
    if body.level is not None:
        check_level(decl.kind, body.level)
        decl.level = body.level
    if body.ended_at is not None:
        check_instant(ctx, body.ended_at, "Fin")
        if body.ended_at < decl.started_at:
            raise HTTPException(UNPROCESSABLE, "Fin avant le début")
        decl.ended_at = body.ended_at
    if "comment" in changes:
        decl.comment = body.comment
    ctx.audit("tension.update", "tension_declaration", decl.id, ", ".join(changes) or None)
    ctx.session.commit()
    names = dict(
        ctx.session.execute(
            select(User.id, User.full_name).where(User.id == decl.declared_by)
        ).all()
    )
    return declaration_out(decl, names)
