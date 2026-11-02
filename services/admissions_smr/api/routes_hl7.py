"""HL7 v2 IHE PAM France movement ingestion (owner: movement-ingest).

* ``POST /api/ingest/hl7``: one ER7 message from the hospital's ADT system (or its
  interface engine), answered with an HL7 ACK. AA -> 200, AE -> 422, AR -> 400 (413 when
  too large): the body is always the ACK, so a sender can read MSA/ERR as usual.
* ``POST /api/ingest/movements``: the same movements, structured, read on screen by the
  computer-use agent.
* ``GET /api/movements``: the journal, pseudonymous, with the rejection rate.

Only the ``ingestion`` service account may post. Neither the message nor any clear
identifier is logged or stored: the journal keeps a keyed digest (HMAC-SHA256, group key
derived for this purpose, see ``domain/pseudonym.py``).
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import replace
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy import func, select

from services.admissions_smr.api.deps import Ctx, ReadCtx, require
from services.admissions_smr.domain.hl7_pam import (
    CANCEL_EVENT,
    DEFAULT_MAX_BYTES,
    ED_CLASS,
    EVENT_LABELS,
    Header,
    Hl7Error,
    ParsedMovement,
    build_ack,
    decode,
    parse,
)
from services.admissions_smr.domain.pseudonym import keyed_digest
from services.admissions_smr.models import Bed, BedPool, Movement
from services.admissions_smr.movement_service import (
    apply_movement,
    record_rejection,
    references,
)
from services.admissions_smr.schemas_liscop import (
    MOVEMENT_BATCH_MAX,
    MovementIn,
    MovementOut,
    MovementPageOut,
    MovementResultOut,
)

router = APIRouter(tags=["ingestion"])

MAX_BYTES = int(os.getenv("ADM_HL7_MAX_BYTES", str(DEFAULT_MAX_BYTES)))
HL7_TYPES = ("x-application/hl7-v2+er7", "application/hl7-v2+er7", "application/hl7-v2")
ACCEPTED_TYPES = frozenset({"text/plain", *HL7_TYPES})
HTTP_STATUS = {"AA": 200, "AE": 422, "AR": 400}

IngestOnly = Annotated[Ctx, Depends(require(frozenset({"ingestion"})))]


async def hl7_body(request: Request) -> tuple[str, bytes]:
    """Read at most MAX_BYTES + 1 bytes, before any database lock is taken."""
    media = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media not in ACCEPTED_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Type de contenu attendu : text/plain ou x-application/hl7-v2+er7",
        )
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BYTES:
            break
    return media, bytes(body[: MAX_BYTES + 1])


def _ack_response(
    media: str,
    header: Header | None,
    code: Literal["AA", "AE", "AR"],
    text: str,
    ctx: Ctx,
    hl7_code: int = 0,
    location: str = "",
    http_status: int | None = None,
) -> Response:
    now = ctx.clock.now()
    ack = build_ack(
        header, code, text, now, f"HOS{now:%Y%m%d%H%M%S}{secrets.token_hex(3)}", hl7_code, location
    )
    return Response(
        ack,
        status_code=http_status or HTTP_STATUS[code],
        media_type=f"{media}; charset=utf-8",
    )


# The body dependency comes first: the message is read before the tenant lock is taken.
@router.post("/ingest/hl7", response_class=Response)
def ingest_hl7(
    message: Annotated[tuple[str, bytes], Depends(hl7_body)], ctx: IngestOnly
) -> Response:
    media, raw = message
    digest = _hl7_digest(ctx, raw)
    try:
        parsed = replace(parse(raw, ctx.clock.zone, MAX_BYTES), digest=digest)
    except Hl7Error as exc:
        header = exc.header
        movement_id = None
        if header is not None and not source_allowed(ctx, header.source_system):
            return _source_refused(media, header, ctx)
        if header is not None:
            row = record_rejection(
                ctx.session,
                ctx.group,
                header.source_system,
                header.control_id,
                header.trigger,
                exc.message,
                ctx.clock.now(),
                digest,
            )
            movement_id = row.id if row else None
        ctx.audit("hl7.rejete", "movement", movement_id, f"{exc.ack_code} {exc.hl7_code}")
        ctx.session.commit()
        too_large = len(raw) > MAX_BYTES
        return _ack_response(
            media,
            header,
            exc.ack_code,
            exc.message,
            ctx,
            exc.hl7_code,
            exc.location,
            413 if too_large else None,
        )
    if not source_allowed(ctx, parsed.source_system):
        return _source_refused(media, parsed.header, ctx)
    result = apply_movement(
        ctx.session,
        ctx.group,
        parsed,
        ctx.clock.now(),
        secret=ctx.settings.pseudonym_secret,
        zone=ctx.clock.zone,
        source="hl7",
        **_window(ctx),
    )
    ctx.audit("hl7.recu", "movement", result.movement_id, f"{parsed.event} {result.status}")
    ctx.session.commit()
    return _ack_response(
        media,
        parsed.header,
        result.ack_code,
        result.message,
        ctx,
        result.hl7_code,
        result.location,
    )


def source_allowed(ctx: Ctx, source_system: str) -> bool:
    """REVIEW S-H1: an ingestion account posts only for its sending systems
    (``users.allowed_sources``, JSON list; empty or NULL = any, for the demo)."""
    try:
        allowed = json.loads(ctx.user.allowed_sources or "[]")
    except ValueError:
        return False  # unreadable setting: fail closed
    if not isinstance(allowed, list):
        return False
    return not allowed or source_system in allowed


SOURCE_REFUSED = "Système émetteur non autorisé pour ce compte d'ingestion"


def _source_refused(media: str, header: Header | None, ctx: Ctx) -> Response:
    """Not journaled: the account must not write under another system's identifiers."""
    ctx.audit("hl7.source_refusee", "movement", None, "AR 207")
    ctx.session.commit()
    return _ack_response(media, header, "AR", SOURCE_REFUSED, ctx, 207, "MSH^1^3", 403)


def _window(ctx: Ctx) -> dict[str, timedelta]:
    """Accepted movement dates around reception (REVIEW S-M1), from the settings."""
    return {
        "max_past": timedelta(days=ctx.settings.movement_max_age_days),
        "max_future": timedelta(hours=ctx.settings.movement_max_future_hours),
    }


def _hl7_digest(ctx: Ctx, raw: bytes) -> str:
    """Keyed digest of the ER7 message (MLLP framing and line endings normalised)."""
    try:
        payload = decode(raw, MAX_BYTES).encode()
    except Hl7Error:
        payload = raw
    return keyed_digest(ctx.settings.pseudonym_secret, ctx.group.id, payload)


def _structured(item: MovementIn, ctx: Ctx) -> ParsedMovement:
    cancel = item.action == "CANCEL"
    event = CANCEL_EVENT[item.event] if cancel else item.event
    patient_class = item.patient_class or (ED_CLASS if item.event == "A04" else None)
    parsed = ParsedMovement(
        source_system=item.source_system,
        control_id=f"{item.movement_ref}:{item.action}",
        event=event,
        action=item.action,
        movement_ref=item.movement_ref,
        occurred_at=item.occurred_at,
        patient_class=patient_class,
        uf_code=item.uf_code,
        room=item.room,
        bed=item.bed,
        facility=item.facility_finess,
        sex=item.sex,
        age=item.age,
        outcome=item.outcome,
        encounter_id=item.encounter_id,
        patient_id=item.patient_id,
    )
    # Keyed digest of the item with its identifiers already replaced by their pseudonyms.
    secret = ctx.settings.pseudonym_secret
    encounter, patient = references(secret, ctx.group.id, parsed)
    # The age shown on screen depends on the day it is read: not part of the content.
    canonical = item.model_dump(mode="json", exclude={"age"})
    canonical |= {"encounter_id": encounter, "patient_id": patient}
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return replace(parsed, digest=keyed_digest(secret, ctx.group.id, payload))


@router.post("/ingest/movements", response_model=list[MovementResultOut])
def ingest_movements(
    items: Annotated[list[MovementIn], Body(max_length=MOVEMENT_BATCH_MAX)], ctx: IngestOnly
) -> list[MovementResultOut]:
    """Idempotent: a movement already received (same system, reference, action) is skipped."""
    out = []
    for item in items:
        if not source_allowed(ctx, item.source_system):
            out.append(MovementResultOut(
                movement_ref=item.movement_ref, status="rejected", message=SOURCE_REFUSED,
                movement_id=None,
            ))  # fmt: skip
            continue
        result = apply_movement(
            ctx.session,
            ctx.group,
            _structured(item, ctx),
            ctx.clock.now(),
            secret=ctx.settings.pseudonym_secret,
            zone=ctx.clock.zone,
            source="agent",
            **_window(ctx),
        )
        out.append(
            MovementResultOut(
                movement_ref=item.movement_ref,
                status=result.status,
                message=result.message,
                movement_id=result.movement_id,
            )
        )
    counts = {s: sum(r.status == s for r in out) for s in {r.status for r in out}}
    ctx.audit("mouvements.agent", "movement", None, str(dict(sorted(counts.items()))))
    ctx.session.commit()
    return out


@router.get("/movements", response_model=MovementPageOut)
def list_movements(
    ctx: ReadCtx,
    status_filter: str | None = Query(default=None, alias="status", max_length=20),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> MovementPageOut:
    scope = [Movement.group_id == ctx.group.id]
    if ctx.site_scope is not None:
        scope.append(Movement.site_id == ctx.site_scope)
    query = select(Movement).where(*scope)
    if status_filter:
        query = query.where(Movement.status == status_filter)
    total = ctx.session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = list(ctx.session.scalars(query.order_by(Movement.id.desc()).limit(limit).offset(offset)))
    pools = {
        p.id: p
        for p in ctx.session.scalars(
            select(BedPool).where(BedPool.id.in_({r.pool_id for r in rows if r.pool_id}))
        )
    }
    beds = {
        b.id: b.label
        for b in ctx.session.scalars(
            select(Bed).where(Bed.id.in_({r.bed_id for r in rows if r.bed_id}))
        )
    }
    since = ctx.clock.now() - timedelta(hours=24)
    counts = dict(
        ctx.session.execute(
            select(Movement.status, func.count())
            .where(*scope, Movement.received_at >= since)
            .group_by(Movement.status)
        ).all()
    )
    last_24h = {str(k): int(v) for k, v in counts.items()}
    received = sum(last_24h.values())
    return MovementPageOut(
        items=[
            MovementOut(
                id=r.id,
                received_at=r.received_at,
                occurred_at=r.occurred_at,
                source_system=r.source_system,
                movement_ref=r.movement_ref,
                event=r.event,
                event_label=EVENT_LABELS.get(r.event, r.event),
                action=r.action,
                status=r.status,
                error=r.error,
                encounter=r.encounter_ref[:8],
                site_id=r.site_id,
                unit_label=(pools[r.pool_id].label or pools[r.pool_id].mention)
                if r.pool_id in pools
                else None,
                bed_label=beds.get(r.bed_id) if r.bed_id else None,
            )
            for r in rows
        ],
        total=total,
        last_24h=last_24h,
        rejection_rate_24h=round(last_24h.get("rejected", 0) / received, 4) if received else None,
    )
