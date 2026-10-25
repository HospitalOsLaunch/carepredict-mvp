"""Assembly between the database and the pure domain logic."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.admissions_smr.api.deps import Ctx
from services.admissions_smr.domain.forecast import (
    DEFAULT_MIN_AT_RISK,
    HazardModel,
    PoolForecast,
    StayRecord,
    fit_hazard,
    forecast_pool,
)
from services.admissions_smr.domain.messages import accord_message, refusal_message
from services.admissions_smr.domain.scoring import (
    DayAvailability,
    Prioritisation,
    RequestFeatures,
    SiteCandidate,
    SiteSuggestion,
    normalise_weights,
    prioritise,
)
from services.admissions_smr.models import AdmissionRequest, RequestEvent, Site, Stay, User
from services.admissions_smr.schemas import (
    EventOut,
    FactorOut,
    RequestDetailOut,
    RequestOut,
    SuggestionOut,
)
from services.admissions_smr.vocab import ALLOWED_TRANSITIONS, REQUEST_STATUSES

HORIZON_DAYS = 14
RESERVING_STATUSES = ("accord", "confirmee")


def split_codes(value: str) -> list[str]:
    return sorted(code for code in value.split(",") if code)


def join_codes(values: list[str] | frozenset[str] | set[str]) -> str:
    return ",".join(sorted(values))


def group_sites(ctx: Ctx, include_inactive: bool = False) -> list[Site]:
    query = select(Site).where(Site.group_id == ctx.group.id).order_by(Site.name)
    if not include_inactive:
        query = query.where(Site.active.is_(True))
    if ctx.site_scope is not None:
        query = query.where(Site.id == ctx.site_scope)
    return list(ctx.session.scalars(query))


def all_group_sites(session: Session, group_id: int) -> list[Site]:
    """Every active site of the group, ignoring the user's site scope (for reorientation)."""
    return list(
        session.scalars(
            select(Site).where(Site.group_id == group_id, Site.active.is_(True)).order_by(Site.name)
        )
    )


def get_site(ctx: Ctx, site_id: int) -> Site:
    site = ctx.session.get(Site, site_id)
    if site is None or site.group_id != ctx.group.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Site introuvable")
    return site


def stay_records(
    session: Session, group_id: int, site_ids: list[int] | None = None
) -> list[StayRecord]:
    query = select(Stay).where(Stay.group_id == group_id)
    if site_ids is not None:
        query = query.where(Stay.site_id.in_(site_ids))
    return [
        StayRecord(
            stay_id=s.id,
            site_id=s.site_id,
            mention=s.mention,
            admission_date=s.admission_date,
            discharge_date=s.discharge_date,
            planned_discharge_date=s.planned_discharge_date,
        )
        for s in session.scalars(query)
    ]


def active_on(records: list[StayRecord], day: date) -> list[StayRecord]:
    """Stays present at the start of ``day`` (still to leave today or later)."""
    return [
        r
        for r in records
        if r.admission_date <= day and (r.discharge_date is None or r.discharge_date >= day)
    ]


def reservations(session: Session, group_id: int) -> dict[tuple[int, str], dict[date, int]]:
    rows = session.scalars(
        select(AdmissionRequest).where(
            AdmissionRequest.group_id == group_id,
            AdmissionRequest.status.in_(RESERVING_STATUSES),
            AdmissionRequest.site_id.is_not(None),
            AdmissionRequest.proposed_date.is_not(None),
        )
    )
    out: dict[tuple[int, str], dict[date, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        assert r.site_id is not None and r.proposed_date is not None
        out[(r.site_id, r.mention_requested)][r.proposed_date] += 1
    return out


@dataclass
class GroupForecast:
    as_of: date
    model: HazardModel
    pools: dict[tuple[int, str], PoolForecast]
    records: list[StayRecord]
    low_data_mentions: list[str]


def build_forecast(
    session: Session, group_id: int, sites: list[Site], as_of: date, horizon: int = HORIZON_DAYS
) -> GroupForecast:
    # Hazards are fitted on the whole group: more data, and mentions behave alike across sites.
    records = stay_records(session, group_id)
    model = fit_hazard(records, as_of)
    current = [
        r
        for r in records
        if r.admission_date <= as_of and (r.discharge_date is None or r.discharge_date > as_of)
    ]
    by_pool: dict[tuple[int, str], list[StayRecord]] = defaultdict(list)
    for r in current:
        by_pool[(r.site_id, r.mention)].append(r)
    reserved = reservations(session, group_id)
    pools: dict[tuple[int, str], PoolForecast] = {}
    for site in sites:
        for pool in site.pools:
            key = (site.id, pool.mention)
            pools[key] = forecast_pool(
                by_pool.get(key, []),
                pool.beds_open,
                as_of,
                horizon,
                model,
                reservations=reserved.get(key, {}),
            )
    low = sorted(m for m, n in model.n_completed.items() if n < DEFAULT_MIN_AT_RISK)
    return GroupForecast(as_of, model, pools, records, low)


def referrer_shares(session: Session, group_id: int, as_of: date) -> dict[int, dict[str, float]]:
    since = as_of - timedelta(days=365)
    rows = session.execute(
        select(Stay.site_id, AdmissionRequest.referrer_facility)
        .join(AdmissionRequest, Stay.request_id == AdmissionRequest.id)
        .where(Stay.group_id == group_id, Stay.admission_date >= since)
    ).all()
    counts: dict[int, Counter[str]] = defaultdict(Counter)
    for site_id, referrer in rows:
        counts[site_id][referrer] += 1
    return {
        site_id: {ref: n / sum(c.values()) for ref, n in c.items()} for site_id, c in counts.items()
    }


def site_candidates(
    session: Session, group_id: int, sites: list[Site], forecast: GroupForecast
) -> list[SiteCandidate]:
    shares = referrer_shares(session, group_id, forecast.as_of)
    out: list[SiteCandidate] = []
    for site in sites:
        availability: dict[str, list[DayAvailability]] = {}
        for pool in site.pools:
            pf = forecast.pools.get((site.id, pool.mention))
            if pf is None:
                continue
            availability[pool.mention] = [
                DayAvailability(d.day, d.free_expected, d.prob_at_least_one_free) for d in pf.days
            ]
        out.append(
            SiteCandidate(
                site_id=site.id,
                site_name=site.name,
                mentions=frozenset(p.mention for p in site.pools if p.beds_open > 0),
                capabilities=frozenset(split_codes(site.capabilities)),
                isolation_rooms_by_mention={p.mention: p.isolation_rooms for p in site.pools},
                availability_by_mention=availability,
                referrer_share=shares.get(site.id, {}),
            )
        )
    return out


def features(req: AdmissionRequest) -> RequestFeatures:
    return RequestFeatures(
        request_id=req.id,
        received_at=req.received_at,
        mention=req.mention_requested,
        care_level=req.care_level,
        isolation_required=req.isolation_required,
        needs=frozenset(split_codes(req.special_needs)),
        desired_date=req.desired_date,
        referrer_facility=req.referrer_facility,
    )


def weights_of(ctx: Ctx) -> dict[str, float]:
    try:
        raw = json.loads(ctx.group.scoring_weights_json or "{}")
    except json.JSONDecodeError:
        raw = {}
    return normalise_weights({k: float(v) for k, v in raw.items()} if isinstance(raw, dict) else {})


def prioritise_request(
    ctx: Ctx, req: AdmissionRequest, candidates: list[SiteCandidate]
) -> Prioritisation:
    return prioritise(
        features(req),
        candidates,
        today=ctx.clock.today(),
        now=ctx.clock.now(),
        weights=weights_of(ctx),
        preferred_site_id=req.site_id,
    )


def suggestion_out(s: SiteSuggestion) -> SuggestionOut:
    return SuggestionOut(
        site_id=s.site_id,
        site_name=s.site_name,
        eligible=s.eligible,
        blockers=s.blockers,
        score=s.score,
        factors=[FactorOut(**f.__dict__) for f in s.factors],
        safe_date=s.safe_date,
        probable_date=s.probable_date,
    )


def request_out(
    ctx: Ctx, req: AdmissionRequest, prio: Prioritisation | None, site_names: dict[int, str]
) -> RequestOut:
    end = req.closed_at or ctx.clock.now()
    waiting = max(0.0, (end - req.received_at).total_seconds() / 3600.0)
    if req.first_response_at is not None:
        waiting = max(0.0, (req.first_response_at - req.received_at).total_seconds() / 3600.0)
    return RequestOut(
        id=req.id,
        source=req.source,
        external_ref=req.external_ref,
        received_at=req.received_at,
        referrer_facility=req.referrer_facility,
        referrer_unit=req.referrer_unit,
        patient_ref=req.patient_ref,
        patient_age=req.patient_age,
        patient_sex=req.patient_sex,
        mention_requested=req.mention_requested,
        clinical_category=req.clinical_category,
        care_level=req.care_level,
        isolation_required=req.isolation_required,
        special_needs=split_codes(req.special_needs),
        desired_date=req.desired_date,
        status=req.status,
        site_id=req.site_id,
        site_name=site_names.get(req.site_id) if req.site_id else None,
        proposed_date=req.proposed_date,
        first_response_at=req.first_response_at,
        closed_at=req.closed_at,
        refusal_reason=req.refusal_reason,
        loss_reason=req.loss_reason,
        notes=req.notes,
        waiting_hours=round(waiting, 1),
        priority=prio.score if prio else 0.0,
        best=suggestion_out(prio.best) if prio and prio.best else None,
    )


def request_detail(
    ctx: Ctx, req: AdmissionRequest, prio: Prioritisation, site_names: dict[int, str]
) -> RequestDetailOut:
    base = request_out(ctx, req, prio, site_names)
    actors = {
        u.id: u.full_name
        for u in ctx.session.scalars(select(User).where(User.group_id == ctx.group.id))
    }
    events = [
        EventOut(
            at=e.at,
            kind=e.kind,
            from_status=e.from_status,
            to_status=e.to_status,
            detail=e.detail,
            actor=actors.get(e.actor_user_id) if e.actor_user_id else None,
        )
        for e in req.events
    ]
    draft: str | None = None
    if req.status in ("accord", "confirmee") and req.site_id and req.proposed_date:
        draft = accord_message(
            site_names.get(req.site_id, "site"),
            req.mention_requested,
            req.proposed_date,
            req.patient_ref,
            req.referrer_unit,
        )
    elif req.status == "refusee" and req.refusal_reason:
        alternative = None
        other = [s for s in prio.suggestions if s.eligible and s.site_id != req.site_id]
        if other and (other[0].safe_date or other[0].probable_date):
            d = other[0].safe_date or other[0].probable_date
            alternative = f"{other[0].site_name}, à partir du {d:%d/%m/%Y}"
        draft = refusal_message(
            site_names.get(req.site_id, "notre établissement")
            if req.site_id
            else "notre établissement",
            req.refusal_reason,
            req.patient_ref,
            None,
            alternative,
        )
    stay_id = ctx.session.scalar(select(Stay.id).where(Stay.request_id == req.id))
    return RequestDetailOut(
        **base.model_dump(),
        suggestions=[suggestion_out(s) for s in prio.suggestions],
        events=events,
        draft_message=draft,
        stay_id=stay_id,
    )


def get_request(ctx: Ctx, request_id: int) -> AdmissionRequest:
    req = ctx.session.get(AdmissionRequest, request_id)
    if req is None or req.group_id != ctx.group.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Demande introuvable")
    if req.site_id is not None and not ctx.can_see_site(req.site_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Demande introuvable")
    return req


def transition(
    ctx: Ctx, req: AdmissionRequest, to_status: str, kind: str, detail: str | None = None
) -> None:
    if to_status not in ALLOWED_TRANSITIONS.get(req.status, frozenset()):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Passage impossible de « {REQUEST_STATUSES[req.status]} » "
            f"à « {REQUEST_STATUSES[to_status]} »",
        )
    now = ctx.clock.now()
    from_status = req.status
    req.status = to_status
    req.updated_at = now
    if to_status in ("accord", "refusee") and req.first_response_at is None:
        req.first_response_at = now
    if to_status in ("admise", "refusee", "perdue"):
        req.closed_at = now
    elif from_status in ("refusee", "perdue"):
        req.closed_at = None
    req.events.append(
        RequestEvent(
            at=now,
            actor_user_id=ctx.user.id,
            kind=kind,
            from_status=from_status,
            to_status=to_status,
            detail=detail,
        )
    )
    ctx.audit(f"demande.{kind}", "admission_request", req.id, f"{from_status} -> {to_status}")


def add_event(ctx: Ctx, req: AdmissionRequest, kind: str, detail: str | None) -> None:
    req.updated_at = ctx.clock.now()
    req.events.append(
        RequestEvent(at=ctx.clock.now(), actor_user_id=ctx.user.id, kind=kind, detail=detail)
    )
    ctx.audit(f"demande.{kind}", "admission_request", req.id, detail)
