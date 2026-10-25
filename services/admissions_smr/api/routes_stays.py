"""Stays (séjours) and their discharge outlook."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from services.admissions_smr.api.deps import UNPROCESSABLE, ReadCtx, WriteCtx
from services.admissions_smr.domain.forecast import StayRecord, fit_hazard, stay_outlook
from services.admissions_smr.models import Site, Stay
from services.admissions_smr.schemas import StayCreate, StayOut, StayUpdate
from services.admissions_smr.service import get_site, stay_records

router = APIRouter(tags=["sejours"])


@router.get("/stays", response_model=list[StayOut])
def list_stays(
    ctx: ReadCtx,
    scope: Literal["presents", "sortis"] = "presents",
    site_id: int | None = None,
    mention: str | None = None,
    limit: int = Query(500, ge=1, le=5000),
) -> list[StayOut]:
    today = ctx.clock.today()
    query = select(Stay).where(Stay.group_id == ctx.group.id)
    if ctx.site_scope is not None:
        query = query.where(Stay.site_id == ctx.site_scope)
    if site_id is not None:
        query = query.where(Stay.site_id == site_id)
    if mention:
        query = query.where(Stay.mention == mention)
    if scope == "presents":
        query = query.where(
            Stay.admission_date <= today,
            (Stay.discharge_date.is_(None)) | (Stay.discharge_date > today),
        ).order_by(Stay.admission_date)
    else:
        query = query.where(Stay.discharge_date.is_not(None), Stay.discharge_date <= today)
        query = query.order_by(Stay.discharge_date.desc())
    rows = list(ctx.session.scalars(query.limit(limit)))
    names = dict(
        ctx.session.execute(select(Site.id, Site.name).where(Site.group_id == ctx.group.id))
        .tuples()
        .all()
    )
    model = (
        fit_hazard(stay_records(ctx.session, ctx.group.id), today) if scope == "presents" else None
    )
    out: list[StayOut] = []
    for s in rows:
        end = s.discharge_date if s.discharge_date and s.discharge_date <= today else today
        prob: float | None = None
        median_day = None
        if model is not None:
            outlook = stay_outlook(
                StayRecord(
                    s.id, s.site_id, s.mention, s.admission_date, None, s.planned_discharge_date
                ),
                today,
                model,
            )
            prob = outlook.prob_within_7_days
            median_day = outlook.median_discharge_day
        out.append(
            StayOut(
                id=s.id,
                site_id=s.site_id,
                site_name=names.get(s.site_id, ""),
                mention=s.mention,
                patient_ref=s.patient_ref,
                admission_date=s.admission_date,
                planned_discharge_date=s.planned_discharge_date,
                discharge_date=s.discharge_date,
                length_of_stay=(end - s.admission_date).days,
                prob_within_7_days=prob,
                median_discharge_day=median_day,
            )
        )
    return out


@router.post("/stays", response_model=StayOut, status_code=201)
def create_stay(body: StayCreate, ctx: WriteCtx) -> StayOut:
    site = get_site(ctx, body.site_id)
    if not ctx.can_see_site(site.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Site hors de votre périmètre")
    if body.admission_date > ctx.clock.today():
        raise HTTPException(UNPROCESSABLE, "L'entrée ne peut être future")
    if not any(p.mention == body.mention for p in site.pools):
        raise HTTPException(status.HTTP_409_CONFLICT, "Mention absente de ce site")
    duplicate = ctx.session.scalar(
        select(Stay.id).where(
            Stay.site_id == site.id,
            Stay.patient_ref == body.patient_ref,
            Stay.admission_date == body.admission_date,
        )
    )
    if duplicate:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ce séjour existe déjà")
    stay = Stay(
        group_id=ctx.group.id,
        site_id=site.id,
        mention=body.mention,
        patient_ref=body.patient_ref,
        admission_date=body.admission_date,
        planned_discharge_date=body.planned_discharge_date,
        created_at=ctx.clock.now(),
        updated_at=ctx.clock.now(),
    )
    ctx.session.add(stay)
    ctx.session.flush()
    ctx.audit("sejour.create", "stay", stay.id, "saisie manuelle")
    ctx.session.commit()
    return StayOut(
        id=stay.id,
        site_id=site.id,
        site_name=site.name,
        mention=stay.mention,
        patient_ref=stay.patient_ref,
        admission_date=stay.admission_date,
        planned_discharge_date=stay.planned_discharge_date,
        discharge_date=None,
        length_of_stay=(ctx.clock.today() - stay.admission_date).days,
        prob_within_7_days=None,
        median_discharge_day=None,
    )


@router.patch("/stays/{stay_id}", response_model=StayOut)
def update_stay(stay_id: int, body: StayUpdate, ctx: WriteCtx) -> StayOut:
    stay = ctx.session.get(Stay, stay_id)
    if stay is None or stay.group_id != ctx.group.id or not ctx.can_see_site(stay.site_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Séjour introuvable")
    today = ctx.clock.today()
    changes: list[str] = []
    if body.clear_planned:
        stay.planned_discharge_date = None
        changes.append("sortie prévue effacée")
    elif body.planned_discharge_date is not None:
        if body.planned_discharge_date < stay.admission_date:
            raise HTTPException(UNPROCESSABLE, "Sortie prévue avant l'entrée")
        stay.planned_discharge_date = body.planned_discharge_date
        changes.append(f"sortie prévue {body.planned_discharge_date:%d/%m/%Y}")
    if body.discharge_date is not None:
        if body.discharge_date < stay.admission_date:
            raise HTTPException(UNPROCESSABLE, "Sortie avant l'entrée")
        if body.discharge_date > today:
            raise HTTPException(UNPROCESSABLE, "La sortie ne peut être future")
        stay.discharge_date = body.discharge_date
        changes.append(f"sortie {body.discharge_date:%d/%m/%Y}")
    if not changes:
        raise HTTPException(UNPROCESSABLE, "Aucune modification")
    stay.updated_at = ctx.clock.now()
    ctx.audit("sejour.update", "stay", stay.id, ", ".join(changes))
    ctx.session.commit()
    site = ctx.session.get(Site, stay.site_id)
    end = stay.discharge_date if stay.discharge_date else today
    return StayOut(
        id=stay.id,
        site_id=stay.site_id,
        site_name=site.name if site else "",
        mention=stay.mention,
        patient_ref=stay.patient_ref,
        admission_date=stay.admission_date,
        planned_discharge_date=stay.planned_discharge_date,
        discharge_date=stay.discharge_date,
        length_of_stay=(end - stay.admission_date).days,
        prob_within_7_days=None,
        median_discharge_day=None,
    )
