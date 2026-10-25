"""Sites and bed pools (installed / open beds with a dated, reasoned history)."""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from services.admissions_smr.api.deps import UNPROCESSABLE, AdminCtx, Ctx, ReadCtx, WriteCtx
from services.admissions_smr.models import BedPool, CapacityChange, Site, Stay
from services.admissions_smr.schemas import PoolOut, PoolUpsert, SiteCreate, SiteOut, SiteUpdate
from services.admissions_smr.service import get_site, group_sites, join_codes, split_codes
from services.admissions_smr.vocab import MENTIONS

router = APIRouter(tags=["sites"])


def occupancy_now(ctx: Ctx) -> Counter[tuple[int, str]]:
    today = ctx.clock.today()
    rows = ctx.session.execute(
        select(Stay.site_id, Stay.mention).where(
            Stay.group_id == ctx.group.id,
            Stay.admission_date <= today,
            (Stay.discharge_date.is_(None)) | (Stay.discharge_date > today),
        )
    ).all()
    return Counter((site_id, mention) for site_id, mention in rows)


def site_out(site: Site, occ: Counter[tuple[int, str]]) -> SiteOut:
    return SiteOut(
        id=site.id,
        name=site.name,
        finess=site.finess,
        city=site.city,
        capabilities=split_codes(site.capabilities),
        active=site.active,
        pools=[
            PoolOut(
                mention=p.mention,
                beds_installed=p.beds_installed,
                beds_open=p.beds_open,
                isolation_rooms=p.isolation_rooms,
                occupied=occ.get((site.id, p.mention), 0),
            )
            for p in site.pools
        ],
    )


@router.get("/sites", response_model=list[SiteOut])
def list_sites(ctx: ReadCtx) -> list[SiteOut]:
    occ = occupancy_now(ctx)
    return [site_out(s, occ) for s in group_sites(ctx, include_inactive=True)]


@router.post("/sites", response_model=SiteOut, status_code=201)
def create_site(body: SiteCreate, ctx: AdminCtx) -> SiteOut:
    exists = ctx.session.scalar(
        select(Site.id).where(Site.group_id == ctx.group.id, Site.name == body.name)
    )
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Un site porte déjà ce nom")
    site = Site(
        group_id=ctx.group.id,
        name=body.name,
        finess=body.finess.upper() if body.finess else None,
        city=body.city,
        capabilities=join_codes(body.capabilities),
        created_at=ctx.clock.now(),
    )
    ctx.session.add(site)
    ctx.session.flush()
    ctx.audit("site.create", "site", site.id, body.name)
    ctx.session.commit()
    ctx.session.refresh(site)
    return site_out(site, Counter())


@router.patch("/sites/{site_id}", response_model=SiteOut)
def update_site(site_id: int, body: SiteUpdate, ctx: AdminCtx) -> SiteOut:
    site = get_site(ctx, site_id)
    changes = body.model_dump(exclude_unset=True)
    if body.name is not None:
        site.name = body.name
    if "finess" in changes:
        site.finess = body.finess.upper() if body.finess else None
    if "city" in changes:
        site.city = body.city
    if body.capabilities is not None:
        site.capabilities = join_codes(body.capabilities)
    if body.active is not None:
        site.active = body.active
    ctx.audit("site.update", "site", site.id, ", ".join(changes))
    ctx.session.commit()
    return site_out(site, occupancy_now(ctx))


@router.put("/sites/{site_id}/pools/{mention}", response_model=SiteOut)
def upsert_pool(site_id: int, mention: str, body: PoolUpsert, ctx: WriteCtx) -> SiteOut:
    if mention not in MENTIONS:
        raise HTTPException(UNPROCESSABLE, "Mention inconnue")
    site = get_site(ctx, site_id)
    if not ctx.can_see_site(site.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Site hors de votre périmètre")
    if body.beds_open > body.beds_installed:
        raise HTTPException(UNPROCESSABLE, "Plus de lits ouverts que de lits installés")
    pool = next((p for p in site.pools if p.mention == mention), None)
    if pool is None:
        if ctx.user.role != "admin_groupe":
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Seul un administrateur crée une mention"
            )
        pool = BedPool(site_id=site.id, mention=mention, beds_installed=0, beds_open=0)
        site.pools.append(pool)
    elif body.beds_installed != pool.beds_installed and ctx.user.role != "admin_groupe":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Seul un administrateur modifie les lits installés"
        )
    pool.beds_installed = body.beds_installed
    pool.beds_open = body.beds_open
    pool.isolation_rooms = body.isolation_rooms
    pool.updated_at = ctx.clock.now()
    ctx.session.add(
        CapacityChange(
            group_id=ctx.group.id,
            site_id=site.id,
            mention=mention,
            effective_date=body.effective_date or ctx.clock.today(),
            beds_installed=body.beds_installed,
            beds_open=body.beds_open,
            reason=body.reason,
            comment=body.comment,
            created_at=ctx.clock.now(),
            created_by=ctx.user.id,
        )
    )
    ctx.audit(
        "lits.update",
        "bed_pool",
        f"{site.id}:{mention}",
        f"installés {body.beds_installed}, ouverts {body.beds_open} ({body.reason})",
    )
    ctx.session.commit()
    ctx.session.refresh(site)
    return site_out(site, occupancy_now(ctx))
