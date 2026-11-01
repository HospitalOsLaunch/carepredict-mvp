"""Bed board: units, rooms, beds, statuses and availability (owner: beds-ed).

Reading is open to the read roles within their site scope. Bed actions (cleaned, block,
unblock, reserve) are for coordination and administrators, audited, and never touch an
occupied bed: a bed is freed only by the stay leaving it (discharge or transfer movement).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.admissions_smr.api.deps import UNPROCESSABLE, Ctx, ReadCtx, WriteCtx
from services.admissions_smr.domain.beds import (
    Availability,
    BedState,
    UnitDeclared,
    add,
    bed_sexes,
    is_usable,
    unit_availability,
)
from services.admissions_smr.models import Bed, BedPool, Site, Stay
from services.admissions_smr.schemas_liscop import (
    AvailabilityOut,
    AvailabilityReportOut,
    BedActionIn,
    BedBoardOut,
    BedOut,
    RoomOut,
    SiteAvailabilityOut,
    SiteBoardOut,
    TensionOut,
    UnitAvailabilityOut,
    UnitBoardOut,
)
from services.admissions_smr.service import get_site, group_sites
from services.admissions_smr.vocab import UNIT_CODES

router = APIRouter(tags=["lits"])

DEFINITIONS = [
    "Lit utilisable : lit actif, libre (ni occupé, ni réservé, ni bloqué, ni à nettoyer) et "
    "qu'au moins un sexe peut occuper compte tenu de sa chambre.",
    "Genre (ROR, nomenclature TRE_R332) : femme = chambre double déjà occupée par une femme "
    "ou lit réservé aux femmes ; homme = idem pour les hommes ; indifférencié = une femme ou "
    "un homme peut y être placé (code ROR 04 « Indéterminé » depuis le 28/08/2025). Les trois "
    "s'additionnent pour donner les lits utilisables.",
    "Isolement : lits utilisables situés en chambre d'isolement.",
    "Fermés : le plus grand des lits bloqués et des fermetures déclarées sur l'unité ; une "
    "fermeture déclarée qui n'est portée sur aucun lit retire un lit utilisable.",
    "Tension (légende LISCOP) : normal si au moins 20 % des lits installés sont utilisables, "
    "critique à 0, tension entre les deux.",
]

# action -> (statuses it applies to, new status)
TRANSITIONS: dict[str, tuple[frozenset[str], str]] = {
    "nettoye": (frozenset({"a_nettoyer"}), "libre"),
    "bloquer": (frozenset({"libre", "a_nettoyer"}), "bloque"),
    "debloquer": (frozenset({"bloque"}), "libre"),
    "reserver": (frozenset({"libre"}), "reserve"),
    "annuler_reservation": (frozenset({"reserve"}), "libre"),
}


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


def bed_out(bed: Bed, state: BedState, accepts: frozenset[str]) -> BedOut:
    return BedOut(
        id=bed.id,
        label=bed.label,
        room=bed.room,
        sex_constraint=bed.sex_constraint,
        isolation=bed.isolation,
        status=bed.status,
        status_reason=bed.status_reason,
        occupant_sex=state.occupant_sex,
        accepts=[] if state.status == "occupe" else sorted(accepts),
        usable=is_usable(state, accepts),
        updated_at=bed.updated_at,
    )


@router.get("/beds", response_model=BedBoardOut)
def bed_board(ctx: ReadCtx, site_id: int | None = None, pool_id: int | None = None) -> BedBoardOut:
    sites = visible_sites(ctx, site_id)
    views = unit_views(ctx.session, ctx.group.id, sites)
    out: list[SiteBoardOut] = []
    for site in sites:
        mine = [v for v in views if v.site.id == site.id]
        if not mine:
            continue
        everything = [s for v in mine for s in v.states]
        sexes = bed_sexes(everything)
        units: list[UnitBoardOut] = []
        for v in mine:
            if pool_id is not None and v.pool.id != pool_id:
                continue
            rooms: dict[str, list[BedOut]] = defaultdict(list)
            for bed, state in zip(v.beds, v.states, strict=True):
                rooms[bed.room].append(bed_out(bed, state, sexes[bed.id]))
            units.append(
                UnitBoardOut(
                    pool_id=v.pool.id,
                    code=v.pool.mention,
                    label=unit_label(v.pool),
                    unit_type=v.pool.unit_type,
                    discipline=v.pool.discipline,
                    availability=availability_out(v.availability),
                    rooms=[RoomOut(room=r, beds=b) for r, b in rooms.items()],
                )
            )
        if units:
            out.append(
                SiteBoardOut(
                    site_id=site.id,
                    site_name=site.name,
                    availability=availability_out(add(v.availability for v in mine)),
                    units=units,
                )
            )
    return BedBoardOut(generated_at=ctx.clock.now(), sites=out)


@router.get("/beds/availability", response_model=AvailabilityReportOut)
def bed_availability(ctx: ReadCtx, site_id: int | None = None) -> AvailabilityReportOut:
    sites = visible_sites(ctx, site_id)
    views = unit_views(ctx.session, ctx.group.id, sites)
    return AvailabilityReportOut(
        generated_at=ctx.clock.now(),
        units=[
            UnitAvailabilityOut(
                site_id=v.site.id,
                site_name=v.site.name,
                pool_id=v.pool.id,
                code=v.pool.mention,
                label=unit_label(v.pool),
                unit_type=v.pool.unit_type,
                discipline=v.pool.discipline,
                ror_unit_id=v.pool.ror_unit_id,
                availability=availability_out(v.availability),
            )
            for v in views
        ],
        sites=[
            SiteAvailabilityOut(
                site_id=s.id,
                site_name=s.name,
                availability=availability_out(
                    add(v.availability for v in views if v.site.id == s.id)
                ),
            )
            for s in sites
            if any(v.site.id == s.id for v in views)
        ],
        definitions=DEFINITIONS,
    )


@router.patch("/beds/{bed_id}", response_model=BedOut)
def act_on_bed(bed_id: int, body: BedActionIn, ctx: WriteCtx) -> BedOut:
    bed = ctx.session.get(Bed, bed_id)
    if bed is None or bed.group_id != ctx.group.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lit introuvable")
    if not ctx.can_see_site(bed.site_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Site hors de votre périmètre")
    if not bed.active:
        raise HTTPException(status.HTTP_409_CONFLICT, "Lit désactivé")
    if bed.status == "occupe" or bed.stay_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Lit occupé : il se libère à la sortie du patient"
        )
    allowed, target = TRANSITIONS[body.action]
    if bed.status not in allowed:
        raise HTTPException(status.HTTP_409_CONFLICT, "Action impossible dans l'état actuel du lit")
    if body.action == "bloquer" and not body.reason:
        raise HTTPException(UNPROCESSABLE, "Indiquez le motif du blocage")
    before = bed.status
    bed.status = target
    bed.status_reason = body.reason if target in ("bloque", "reserve") else None
    bed.updated_at = ctx.clock.now()
    detail = f"{before} → {target}" + (f" ({body.reason})" if body.reason else "")
    ctx.audit(f"lit.{body.action}", "bed", bed.id, detail)
    ctx.session.commit()
    [state] = bed_states(ctx.session, [bed])
    roommates = bed_states(
        ctx.session,
        list(
            ctx.session.scalars(select(Bed).where(Bed.site_id == bed.site_id, Bed.room == bed.room))
        ),
    )
    return bed_out(bed, state, bed_sexes(roommates)[bed.id])
