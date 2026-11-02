"""Bed board: units, rooms, beds, statuses and availability (owner: beds-ed).

Reading is open to the read roles within their site scope. Bed actions (cleaned, block,
unblock, reserve) are for coordination and administrators, audited, and never touch an
occupied bed: a bed is freed only by the stay leaving it (discharge or transfer movement).
"""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from services.admissions_smr.api.deps import UNPROCESSABLE, ReadCtx, WriteCtx
from services.admissions_smr.domain.beds import (
    BedState,
    add,
    bed_sexes,
    is_usable,
)
from services.admissions_smr.liscop_service import (
    availability_out,
    bed_states,
    unit_label,
    unit_views,
    visible_sites,
)
from services.admissions_smr.models import Bed
from services.admissions_smr.schemas_liscop import (
    AvailabilityReportOut,
    BedActionIn,
    BedBoardOut,
    BedOut,
    RoomOut,
    SiteAvailabilityOut,
    SiteBoardOut,
    UnitAvailabilityOut,
    UnitBoardOut,
)
from services.admissions_smr.vocab import BED_BLOCK_REASONS

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
    blocking = body.action == "bloquer"
    if blocking and body.reason not in BED_BLOCK_REASONS:
        raise HTTPException(UNPROCESSABLE, "Choisissez le motif du blocage dans la liste")
    note = (body.note or "").strip() or None
    before = bed.status
    bed.status = target
    if blocking:
        assert body.reason is not None
        label = BED_BLOCK_REASONS[body.reason]
        bed.status_reason = f"{label} : {note}" if note else label
    else:
        bed.status_reason = note if target == "reserve" else None
    bed.updated_at = ctx.clock.now()
    # The audit keeps the code only: the free note may hold a name.
    detail = f"{before} → {target}" + (f" ({body.reason})" if blocking else "")
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
