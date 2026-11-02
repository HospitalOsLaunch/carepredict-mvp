"""Loaders shared by the LISCOP routes (beds, emergency department, ROR / ORU export).

Kept out of the route modules so that no route imports another one.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from services.admissions_smr.api.deps import Ctx
from services.admissions_smr.domain.beds import (
    Availability,
    BedState,
    UnitDeclared,
    unit_availability,
)
from services.admissions_smr.domain.ed import AdmittedStay, Declared, Visit
from services.admissions_smr.models import Bed, BedPool, EdSnapshot, EdVisit, Site, Stay
from services.admissions_smr.schemas_liscop import AvailabilityOut, TensionOut
from services.admissions_smr.service import get_site, group_sites
from services.admissions_smr.vocab import UNIT_CODES

# --- beds ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class UnitView:
    site: Site
    pool: BedPool
    beds: list[Bed]
    states: list[BedState]
    availability: Availability


def bed_states(session: Session, beds: Sequence[Bed]) -> list[BedState]:
    stay_ids = [b.stay_id for b in beds if b.stay_id is not None]
    rows = session.execute(select(Stay.id, Stay.patient_sex).where(Stay.id.in_(stay_ids)))
    sexes = dict(rows.all())
    return [
        BedState(
            id=b.id,
            site_id=b.site_id,
            pool_id=b.pool_id,
            room=b.room,
            label=b.label,
            sex_constraint=b.sex_constraint,
            isolation=b.isolation,
            status=b.status,
            active=b.active,
            occupant_sex=sexes.get(b.stay_id) if b.stay_id is not None else None,
        )
        for b in beds
    ]


def unit_views(session: Session, group_id: int, sites: Sequence[Site]) -> list[UnitView]:
    """Every unit with beds on these sites, with its availability. For the ROR/ORU export."""
    beds = list(
        session.scalars(
            select(Bed)
            .where(Bed.group_id == group_id, Bed.site_id.in_([s.id for s in sites]))
            .order_by(Bed.room, Bed.label)
        )
    )
    states = bed_states(session, beds)
    by_pool: dict[int, list[int]] = defaultdict(list)
    for i, b in enumerate(beds):
        by_pool[b.pool_id].append(i)
    # A room may straddle two units: roommates are looked up on the whole site.
    states_by_site: dict[int, list[BedState]] = defaultdict(list)
    for st in states:
        states_by_site[st.site_id].append(st)
    out: list[UnitView] = []
    for site in sites:
        for pool in site.pools:
            idx = by_pool.get(pool.id)
            if not idx:
                continue
            declared = UnitDeclared(
                pool.id,
                pool.beds_installed,
                pool.beds_open,
                pool.extra_beds,
                pool.crisis_reserved_beds,
            )
            out.append(
                UnitView(
                    site=site,
                    pool=pool,
                    beds=[beds[i] for i in idx],
                    states=[states[i] for i in idx],
                    availability=unit_availability(declared, states_by_site[site.id]),
                )
            )
    return out


def availability_out(a: Availability) -> AvailabilityOut:
    t = a.tension
    return AvailabilityOut(
        installed=a.installed,
        occupied=a.occupied,
        reserved=a.reserved,
        cleaning=a.cleaning,
        blocked=a.blocked,
        closed=a.closed,
        usable=a.usable,
        female=a.female,
        male=a.male,
        either=a.either,
        isolation=a.isolation,
        sex_conflict=a.sex_conflict,
        extra_beds=a.extra_beds,
        crisis_reserved_beds=a.crisis_reserved_beds,
        tension=TensionOut(level=t.level, availability_rate=t.availability_rate),
    )


def unit_label(pool: BedPool) -> str:
    return pool.label or UNIT_CODES.get(pool.mention, pool.mention)


def visible_sites(ctx: Ctx, site_id: int | None) -> list[Site]:
    if site_id is None:
        return group_sites(ctx)
    site = get_site(ctx, site_id)
    if not ctx.can_see_site(site.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Site hors de votre périmètre")
    return [site]


# --- emergency department -----------------------------------------------------------------


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
