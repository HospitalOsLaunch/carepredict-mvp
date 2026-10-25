"""Stays (séjours): discharge outlook, care level and planned discharge history."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from services.admissions_smr.api.deps import UNPROCESSABLE, Ctx, ReadCtx, WriteCtx
from services.admissions_smr.domain.forecast import (
    DEFAULT_PLAN_SLIP,
    HazardModel,
    StayRecord,
    estimate_plan_slip,
    fit_hazard,
    stay_outlook,
)
from services.admissions_smr.models import Site, Stay
from services.admissions_smr.schemas import StayCreate, StayOut, StayUpdate
from services.admissions_smr.service import get_site, plan_history, record_plan, stay_records

router = APIRouter(tags=["sejours"])


def stay_out(
    s: Stay,
    site_name: str,
    today: date,
    model: HazardModel | None,
    slip: Mapping[int, float] = DEFAULT_PLAN_SLIP,
) -> StayOut:
    end = s.discharge_date if s.discharge_date and s.discharge_date <= today else today
    prob: float | None = None
    median_day: date | None = None
    if model is not None and s.discharge_date is None:
        record = StayRecord(
            s.id,
            s.site_id,
            s.mention,
            s.admission_date,
            None,
            s.planned_discharge_date,
            s.care_level,
        )
        outlook = stay_outlook(record, today, model, plan_slip=slip)
        prob = outlook.prob_within_7_days
        median_day = outlook.median_discharge_day
    return StayOut(
        id=s.id,
        site_id=s.site_id,
        site_name=site_name,
        mention=s.mention,
        patient_ref=s.patient_ref,
        admission_date=s.admission_date,
        planned_discharge_date=s.planned_discharge_date,
        discharge_date=s.discharge_date,
        length_of_stay=(end - s.admission_date).days,
        care_level=s.care_level,
        prob_within_7_days=prob,
        median_discharge_day=median_day,
        plan_changes=len(s.plan_changes),
    )


def _site_names(ctx: Ctx) -> dict[int, str]:
    rows = ctx.session.execute(select(Site.id, Site.name).where(Site.group_id == ctx.group.id))
    return dict(rows.tuples().all())


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
    names = _site_names(ctx)
    model = None
    slip: Mapping[int, float] = DEFAULT_PLAN_SLIP
    if scope == "presents":
        records = stay_records(ctx.session, ctx.group.id)
        plans = plan_history(ctx.session, ctx.group.id)
        model = fit_hazard(records, today, plans=plans or None)
        slip = estimate_plan_slip(records, plans, today).weights
    return [stay_out(s, names.get(s.site_id, ""), today, model, slip) for s in rows]


@router.post("/stays", response_model=StayOut, status_code=201)
def create_stay(body: StayCreate, ctx: WriteCtx) -> StayOut:
    site = get_site(ctx, body.site_id)
    if not ctx.can_see_site(site.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Site hors de votre périmètre")
    if body.admission_date > ctx.clock.today():
        raise HTTPException(UNPROCESSABLE, "L'entrée ne peut être future")
    if body.planned_discharge_date and body.planned_discharge_date < body.admission_date:
        raise HTTPException(UNPROCESSABLE, "Sortie prévue avant l'entrée")
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
        care_level=body.care_level,
        created_at=ctx.clock.now(),
        updated_at=ctx.clock.now(),
    )
    ctx.session.add(stay)
    if body.planned_discharge_date is not None:
        record_plan(ctx, stay, body.planned_discharge_date, "saisie")
    ctx.session.flush()
    ctx.audit("sejour.create", "stay", stay.id, "saisie manuelle")
    ctx.session.commit()
    return stay_out(stay, site.name, ctx.clock.today(), None)


@router.patch("/stays/{stay_id}", response_model=StayOut)
def update_stay(stay_id: int, body: StayUpdate, ctx: WriteCtx) -> StayOut:
    stay = ctx.session.get(Stay, stay_id)
    if stay is None or stay.group_id != ctx.group.id or not ctx.can_see_site(stay.site_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Séjour introuvable")
    today = ctx.clock.today()
    changes: list[str] = []
    if body.clear_planned:
        record_plan(ctx, stay, None, "saisie")
        changes.append("sortie prévue effacée")
    elif body.planned_discharge_date is not None:
        if body.planned_discharge_date < stay.admission_date:
            raise HTTPException(UNPROCESSABLE, "Sortie prévue avant l'entrée")
        record_plan(ctx, stay, body.planned_discharge_date, "saisie")
        changes.append(f"sortie prévue {body.planned_discharge_date:%d/%m/%Y}")
    if body.discharge_date is not None:
        if body.discharge_date < stay.admission_date:
            raise HTTPException(UNPROCESSABLE, "Sortie avant l'entrée")
        if body.discharge_date > today:
            raise HTTPException(UNPROCESSABLE, "La sortie ne peut être future")
        stay.discharge_date = body.discharge_date
        changes.append(f"sortie {body.discharge_date:%d/%m/%Y}")
    if body.care_level is not None:
        stay.care_level = body.care_level
        changes.append(f"charge en soins niveau {body.care_level}")
    if not changes:
        raise HTTPException(UNPROCESSABLE, "Aucune modification")
    stay.updated_at = ctx.clock.now()
    ctx.audit("sejour.update", "stay", stay.id, ", ".join(changes))
    ctx.session.commit()
    site = ctx.session.get(Site, stay.site_id)
    return stay_out(stay, site.name if site else "", today, None)
