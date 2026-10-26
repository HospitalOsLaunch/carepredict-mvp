"""Admission requests: prioritised queue, detail, and the one-click response workflow."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import or_, select

from services.admissions_smr.api.deps import UNPROCESSABLE, Ctx, IngestCtx, ReadCtx, WriteCtx
from services.admissions_smr.api.routes_agent import enqueue_portal_reply
from services.admissions_smr.domain.scoring import SiteCandidate
from services.admissions_smr.models import AdmissionRequest, RequestEvent, Stay
from services.admissions_smr.schemas import (
    AccordIn,
    AdmitIn,
    ConfirmIn,
    LoseIn,
    NoteIn,
    RefuseIn,
    ReopenIn,
    ReorientIn,
    RequestCreate,
    RequestDetailOut,
    RequestOut,
    StartIn,
)
from services.admissions_smr.service import (
    add_event,
    all_group_sites,
    build_forecast,
    get_request,
    get_site,
    join_codes,
    prioritise_request,
    record_plan,
    request_detail,
    request_out,
    site_candidates,
    transition,
)
from services.admissions_smr.task_state import decision_changed
from services.admissions_smr.vocab import (
    LOSS_REASONS,
    MENTIONS,
    OPEN_STATUSES,
    REFUSAL_REASONS,
    REQUEST_SOURCES,
)

router = APIRouter(tags=["demandes"])


def _context(ctx: Ctx) -> tuple[list[SiteCandidate], dict[int, str]]:
    sites = all_group_sites(ctx.session, ctx.group.id)
    forecast = build_forecast(ctx.session, ctx.group.id, sites, ctx.clock.today())
    candidates = site_candidates(ctx.session, ctx.group.id, sites, forecast)
    return candidates, {s.id: s.name for s in sites}


@router.get("/requests", response_model=list[RequestOut])
def list_requests(
    ctx: ReadCtx,
    scope: Literal["ouvertes", "a_traiter", "fermees", "toutes"] = "ouvertes",
    site_id: int | None = None,
    mention: str | None = None,
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(300, ge=1, le=2000),
) -> list[RequestOut]:
    query = select(AdmissionRequest).where(AdmissionRequest.group_id == ctx.group.id)
    if scope == "ouvertes":
        query = query.where(AdmissionRequest.status.in_(OPEN_STATUSES))
    elif scope == "a_traiter":
        query = query.where(AdmissionRequest.status.in_(("nouvelle", "en_etude")))
    elif scope == "fermees":
        query = query.where(AdmissionRequest.status.not_in(OPEN_STATUSES))
    if ctx.site_scope is not None:
        query = query.where(
            or_(AdmissionRequest.site_id.is_(None), AdmissionRequest.site_id == ctx.site_scope)
        )
    if site_id is not None:
        query = query.where(AdmissionRequest.site_id == site_id)
    if mention:
        query = query.where(AdmissionRequest.mention_requested == mention)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(
            or_(
                AdmissionRequest.patient_ref.ilike(like),
                AdmissionRequest.referrer_facility.ilike(like),
                AdmissionRequest.external_ref.ilike(like),
            )
        )
    query = query.order_by(AdmissionRequest.received_at.desc()).limit(limit)
    rows = list(ctx.session.scalars(query))
    candidates, names = _context(ctx)
    out = []
    for req in rows:
        prio = prioritise_request(ctx, req, candidates) if req.status in OPEN_STATUSES else None
        out.append(request_out(ctx, req, prio, names))
    if scope in ("ouvertes", "a_traiter"):
        order = {"nouvelle": 0, "en_etude": 0, "accord": 1, "confirmee": 2}
        out.sort(key=lambda r: (order.get(r.status, 3), -r.priority, r.received_at))
    return out


def create_request(ctx: Ctx, body: RequestCreate, kind: str = "recue") -> AdmissionRequest:
    if body.site_id is not None:
        get_site(ctx, body.site_id)
    now = ctx.clock.now()
    received = body.received_at or now
    if received.tzinfo is None:
        raise HTTPException(UNPROCESSABLE, "received_at doit avoir un fuseau")
    if received > now:
        raise HTTPException(UNPROCESSABLE, "Date de réception dans le futur")
    req = AdmissionRequest(
        group_id=ctx.group.id,
        source=body.source,
        external_ref=body.external_ref,
        received_at=received,
        referrer_facility=body.referrer_facility.strip(),
        referrer_unit=body.referrer_unit,
        patient_ref=body.patient_ref,
        patient_age=body.patient_age,
        patient_sex=body.patient_sex,
        mention_requested=body.mention_requested,
        clinical_category=body.clinical_category,
        care_level=body.care_level,
        isolation_required=body.isolation_required,
        special_needs=join_codes(body.special_needs),
        desired_date=body.desired_date,
        site_id=body.site_id,
        notes=body.notes,
        status="nouvelle",
        created_at=now,
        updated_at=now,
    )
    req.events.append(
        RequestEvent(
            at=received,
            actor_user_id=ctx.user.id,
            kind=kind,
            to_status="nouvelle",
            detail=f"Reçue par {REQUEST_SOURCES[body.source]}",
        )
    )
    ctx.session.add(req)
    ctx.session.flush()
    ctx.audit("demande.create", "admission_request", req.id, body.source)
    return req


@router.post("/requests", response_model=RequestDetailOut, status_code=201)
def post_request(body: RequestCreate, ctx: WriteCtx) -> RequestDetailOut:
    if body.external_ref and _find_external(ctx, body.source, body.external_ref):
        raise HTTPException(status.HTTP_409_CONFLICT, "Cette demande existe déjà")
    req = create_request(ctx, body)
    ctx.session.commit()
    return _detail(ctx, req)


def _find_external(ctx: Ctx, source: str, external_ref: str) -> AdmissionRequest | None:
    return ctx.session.scalar(
        select(AdmissionRequest).where(
            AdmissionRequest.group_id == ctx.group.id,
            AdmissionRequest.source == source,
            AdmissionRequest.external_ref == external_ref,
        )
    )


class IngestOut(BaseModel):
    id: int
    created: bool


@router.post("/ingest/requests", response_model=IngestOut, tags=["ingestion"])
def ingest_request(body: RequestCreate, ctx: IngestCtx) -> IngestOut:
    """Idempotent entry point for the computer-use agent (ViaTrajectoire, mail, fax).

    A request already received with the same (source, external_ref) is not duplicated.
    """
    if not body.external_ref:
        raise HTTPException(UNPROCESSABLE, "external_ref est obligatoire")
    existing = _find_external(ctx, body.source, body.external_ref)
    if existing is not None:
        return IngestOut(id=existing.id, created=False)
    req = create_request(ctx, body, kind="recue_auto")
    ctx.session.commit()
    return IngestOut(id=req.id, created=True)


def _detail(ctx: Ctx, req: AdmissionRequest) -> RequestDetailOut:
    candidates, names = _context(ctx)
    prio = prioritise_request(ctx, req, candidates)
    return request_detail(ctx, req, prio, names)


@router.get("/requests/{request_id}", response_model=RequestDetailOut)
def get_request_detail(request_id: int, ctx: ReadCtx) -> RequestDetailOut:
    return _detail(ctx, get_request(ctx, request_id))


def _assign_site(ctx: Ctx, req: AdmissionRequest, site_id: int) -> None:
    site = get_site(ctx, site_id)
    if not site.active:
        raise HTTPException(status.HTTP_409_CONFLICT, "Site inactif")
    if not any(p.mention == req.mention_requested and p.beds_open > 0 for p in site.pools):
        label = MENTIONS[req.mention_requested]
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{site.name} n'a pas de lit ouvert en mention « {label} »"
        )
    req.site_id = site.id


@router.post("/requests/{request_id}/start", response_model=RequestDetailOut)
def start(request_id: int, body: StartIn, ctx: WriteCtx) -> RequestDetailOut:
    req = get_request(ctx, request_id)
    if body.site_id is not None:
        _assign_site(ctx, req, body.site_id)
    transition(ctx, req, "en_etude", "etude")
    ctx.session.commit()
    return _detail(ctx, req)


@router.post("/requests/{request_id}/accord", response_model=RequestDetailOut)
def accord(request_id: int, body: AccordIn, ctx: WriteCtx) -> RequestDetailOut:
    req = get_request(ctx, request_id)
    if body.proposed_date < ctx.clock.today():
        raise HTTPException(UNPROCESSABLE, "La date proposée est passée")
    _assign_site(ctx, req, body.site_id)
    req.proposed_date = body.proposed_date
    req.refusal_reason = None
    transition(ctx, req, "accord", "accord", f"Entrée proposée le {body.proposed_date:%d/%m/%Y}")
    enqueue_portal_reply(ctx, req)
    ctx.session.commit()
    return _detail(ctx, req)


@router.post("/requests/{request_id}/refuse", response_model=RequestDetailOut)
def refuse(request_id: int, body: RefuseIn, ctx: WriteCtx) -> RequestDetailOut:
    req = get_request(ctx, request_id)
    req.refusal_reason = body.reason
    req.proposed_date = None
    detail = REFUSAL_REASONS[body.reason] + (f" — {body.comment}" if body.comment else "")
    transition(ctx, req, "refusee", "refus", detail)
    enqueue_portal_reply(ctx, req)
    ctx.session.commit()
    return _detail(ctx, req)


@router.post("/requests/{request_id}/confirm", response_model=RequestDetailOut)
def confirm(request_id: int, body: ConfirmIn, ctx: WriteCtx) -> RequestDetailOut:
    req = get_request(ctx, request_id)
    if body.proposed_date is not None:
        if body.proposed_date < ctx.clock.today():
            raise HTTPException(UNPROCESSABLE, "La date est passée")
        req.proposed_date = body.proposed_date
    transition(
        ctx,
        req,
        "confirmee",
        "confirmation",
        f"Entrée prévue le {req.proposed_date:%d/%m/%Y}" if req.proposed_date else None,
    )
    enqueue_portal_reply(ctx, req)
    ctx.session.commit()
    return _detail(ctx, req)


@router.post("/requests/{request_id}/admit", response_model=RequestDetailOut)
def admit(request_id: int, body: AdmitIn, ctx: WriteCtx) -> RequestDetailOut:
    req = get_request(ctx, request_id)
    if req.site_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Aucun site attribué à cette demande")
    if body.admission_date > ctx.clock.today():
        raise HTTPException(UNPROCESSABLE, "L'entrée ne peut être future")
    if body.planned_discharge_date and body.planned_discharge_date < body.admission_date:
        raise HTTPException(UNPROCESSABLE, "Sortie prévue avant l'entrée")
    transition(ctx, req, "admise", "admission", f"Entrée le {body.admission_date:%d/%m/%Y}")
    stay = Stay(
        group_id=ctx.group.id,
        site_id=req.site_id,
        mention=req.mention_requested,
        patient_ref=req.patient_ref,
        admission_date=body.admission_date,
        care_level=body.care_level or req.care_level,
        request_id=req.id,
        created_at=ctx.clock.now(),
        updated_at=ctx.clock.now(),
    )
    ctx.session.add(stay)
    if body.planned_discharge_date is not None:
        record_plan(ctx, stay, body.planned_discharge_date, "admission")
    ctx.session.flush()
    ctx.audit("sejour.create", "stay", stay.id, f"depuis la demande {req.id}")
    ctx.session.commit()
    return _detail(ctx, req)


@router.post("/requests/{request_id}/lose", response_model=RequestDetailOut)
def lose(request_id: int, body: LoseIn, ctx: WriteCtx) -> RequestDetailOut:
    req = get_request(ctx, request_id)
    req.loss_reason = body.reason
    detail = LOSS_REASONS[body.reason] + (f" — {body.comment}" if body.comment else "")
    transition(ctx, req, "perdue", "perte", detail)
    ctx.session.commit()
    return _detail(ctx, req)


@router.post("/requests/{request_id}/reopen", response_model=RequestDetailOut)
def reopen(request_id: int, body: ReopenIn, ctx: WriteCtx) -> RequestDetailOut:
    req = get_request(ctx, request_id)
    req.refusal_reason = None
    req.loss_reason = None
    transition(ctx, req, "en_etude", "reouverture", body.comment)
    ctx.session.commit()
    return _detail(ctx, req)


@router.post("/requests/{request_id}/reorient", response_model=RequestDetailOut)
def reorient(request_id: int, body: ReorientIn, ctx: WriteCtx) -> RequestDetailOut:
    req = get_request(ctx, request_id)
    if req.status in ("admise",):
        raise HTTPException(status.HTTP_409_CONFLICT, "Demande déjà admise")
    previous = req.site_id
    if previous == body.site_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "La demande est déjà sur ce site")
    _assign_site(ctx, req, body.site_id)
    site_name = get_site(ctx, body.site_id).name
    if req.status in ("accord", "confirmee", "refusee", "perdue"):
        # A new site has to give its own answer; the previous promise no longer holds.
        req.proposed_date = None
        req.refusal_reason = None
        req.loss_reason = None
        transition(ctx, req, "en_etude", "reorientation", f"Vers {site_name}")
    else:
        decision_changed(ctx, req)
        add_event(ctx, req, "reorientation", f"Vers {site_name}")
    ctx.session.commit()
    return _detail(ctx, req)


@router.post("/requests/{request_id}/notes", response_model=RequestDetailOut)
def add_note(request_id: int, body: NoteIn, ctx: WriteCtx) -> RequestDetailOut:
    req = get_request(ctx, request_id)
    add_event(ctx, req, "note", body.text)
    ctx.session.commit()
    return _detail(ctx, req)
