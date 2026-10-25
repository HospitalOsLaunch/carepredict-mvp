"""CSV onboarding: templates, dry-run validation, all-or-nothing commit."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from sqlalchemy import select

from services.admissions_smr.api.deps import AdminCtx, Ctx
from services.admissions_smr.domain.imports import (
    TEMPLATES,
    PoolRow,
    RequestRow,
    RowError,
    StayRow,
    parse_csv,
)
from services.admissions_smr.models import (
    AdmissionRequest,
    BedPool,
    CapacityChange,
    RequestEvent,
    Site,
    Stay,
)
from services.admissions_smr.schemas import ImportErrorOut, ImportIn, ImportOut
from services.admissions_smr.service import join_codes

router = APIRouter(tags=["imports"])

Kind = Literal["lits", "sejours", "demandes"]

_EXAMPLES: dict[str, str] = {
    "lits": "SMR Les Tilleuls;750000001;Lyon;geriatrie;40;36;4;oxygene|nutrition_enterale",
    "sejours": "SMR Les Tilleuls;geriatrie;PAT-000123;02/10/2026;;",
    "demandes": (
        "viatrajectoire;VT-2026-001234;24/10/2026 14:05;CH de Villefranche;Médecine polyvalente;"
        "PAT-000456;84;F;geriatrie;Fracture du col fémoral opérée;3;non;oxygene;28/10/2026"
    ),
}


@router.get("/imports/templates/{kind}", response_class=PlainTextResponse)
def template(kind: Kind) -> PlainTextResponse:
    body = ";".join(TEMPLATES[kind]) + "\n" + _EXAMPLES[kind] + "\n"
    return PlainTextResponse(
        "﻿" + body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="modele_{kind}.csv"'},
    )


@router.post("/imports/{kind}", response_model=ImportOut)
def run_import(kind: Kind, body: ImportIn, ctx: AdminCtx) -> ImportOut:
    parsed = parse_csv(kind, body.csv_text, ctx.settings.timezone)
    errors = list(parsed.errors)
    created = updated = 0
    if not errors:
        if kind == "lits":
            created, updated = _apply_pools(ctx, [r for r in parsed.rows if isinstance(r, PoolRow)])
        elif kind == "sejours":
            created, updated = _apply_stays(
                ctx, [r for r in parsed.rows if isinstance(r, StayRow)], errors
            )
        else:
            created, updated = _apply_requests(
                ctx, [r for r in parsed.rows if isinstance(r, RequestRow)], errors
            )
    committed = False
    if errors or body.dry_run:
        ctx.session.rollback()
    else:
        ctx.audit(f"import.{kind}", "import", None, f"{created} créés, {updated} mis à jour")
        ctx.session.commit()
        committed = True
    return ImportOut(
        kind=kind,
        dry_run=body.dry_run,
        rows=len(parsed.rows),
        created=created if not errors else 0,
        updated=updated if not errors else 0,
        errors=[
            ImportErrorOut(line=e.line, column=e.column, message=e.message) for e in errors[:500]
        ],
        committed=committed,
    )


def _sites_by_name(ctx: Ctx) -> dict[str, Site]:
    return {
        s.name.strip().lower(): s
        for s in ctx.session.scalars(select(Site).where(Site.group_id == ctx.group.id))
    }


def _apply_pools(ctx: Ctx, rows: list[PoolRow]) -> tuple[int, int]:
    sites = _sites_by_name(ctx)
    created = updated = 0
    for row in rows:
        key = row.site.strip().lower()
        site = sites.get(key)
        if site is None:
            site = Site(group_id=ctx.group.id, name=row.site.strip(), created_at=ctx.clock.now())
            ctx.session.add(site)
            sites[key] = site
        if row.finess:
            site.finess = row.finess.upper()
        if row.city:
            site.city = row.city
        if row.capabilities:
            site.capabilities = join_codes(row.capabilities)
        ctx.session.flush()
        pool = next((p for p in site.pools if p.mention == row.mention), None)
        if pool is None:
            pool = BedPool(site_id=site.id, mention=row.mention, beds_installed=0, beds_open=0)
            site.pools.append(pool)
            created += 1
        else:
            updated += 1
        pool.beds_installed = row.beds_installed
        pool.beds_open = row.beds_open
        pool.isolation_rooms = row.isolation_rooms
        pool.updated_at = ctx.clock.now()
        ctx.session.add(
            CapacityChange(
                group_id=ctx.group.id,
                site_id=site.id,
                mention=row.mention,
                effective_date=ctx.clock.today(),
                beds_installed=row.beds_installed,
                beds_open=row.beds_open,
                # An import cannot know why beds are closed: never guess "staffing".
                reason="autre",
                comment="Import CSV : motif de fermeture à préciser",
                created_at=ctx.clock.now(),
                created_by=ctx.user.id,
            )
        )
    return created, updated


def _apply_stays(ctx: Ctx, rows: list[StayRow], errors: list[RowError]) -> tuple[int, int]:
    sites = _sites_by_name(ctx)
    today = ctx.clock.today()
    created = updated = 0
    for row in rows:
        site = sites.get(row.site.strip().lower())
        if site is None:
            errors.append(
                RowError(
                    row.line, "site", f"Site inconnu : « {row.site} » (importez les lits d'abord)"
                )
            )
            continue
        if not any(p.mention == row.mention for p in site.pools):
            errors.append(RowError(row.line, "mention", f"Mention absente du site {site.name}"))
            continue
        if row.admission_date > today or (row.discharge_date and row.discharge_date > today):
            errors.append(
                RowError(row.line, "date_entree", "Dates futures refusées pour un séjour réel")
            )
            continue
        stay = ctx.session.scalar(
            select(Stay).where(
                Stay.site_id == site.id,
                Stay.patient_ref == row.patient_ref,
                Stay.admission_date == row.admission_date,
            )
        )
        if stay is None:
            ctx.session.add(
                Stay(
                    group_id=ctx.group.id,
                    site_id=site.id,
                    mention=row.mention,
                    patient_ref=row.patient_ref,
                    admission_date=row.admission_date,
                    planned_discharge_date=row.planned_discharge_date,
                    discharge_date=row.discharge_date,
                    created_at=ctx.clock.now(),
                    updated_at=ctx.clock.now(),
                )
            )
            ctx.session.flush()
            created += 1
        else:
            stay.mention = row.mention
            stay.planned_discharge_date = row.planned_discharge_date
            stay.discharge_date = row.discharge_date
            stay.updated_at = ctx.clock.now()
            updated += 1
    return created, updated


def _apply_requests(ctx: Ctx, rows: list[RequestRow], errors: list[RowError]) -> tuple[int, int]:
    now = ctx.clock.now()
    created = updated = 0
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if row.received_at > now:
            errors.append(RowError(row.line, "recue_le", "Date de réception dans le futur"))
            continue
        existing = None
        if row.external_ref:
            key = (row.source, row.external_ref)
            if key in seen:
                errors.append(
                    RowError(row.line, "ref_externe", "Référence en double dans le fichier")
                )
                continue
            seen.add(key)
            existing = ctx.session.scalar(
                select(AdmissionRequest).where(
                    AdmissionRequest.group_id == ctx.group.id,
                    AdmissionRequest.source == row.source,
                    AdmissionRequest.external_ref == row.external_ref,
                )
            )
        if existing is not None:
            updated += 1
            continue  # never overwrite a request already being handled
        req = AdmissionRequest(
            group_id=ctx.group.id,
            source=row.source,
            external_ref=row.external_ref,
            received_at=row.received_at,
            referrer_facility=row.referrer_facility,
            referrer_unit=row.referrer_unit,
            patient_ref=row.patient_ref,
            patient_age=row.patient_age,
            patient_sex=row.patient_sex,
            mention_requested=row.mention,
            clinical_category=row.clinical_category,
            care_level=row.care_level,
            isolation_required=row.isolation_required,
            special_needs=join_codes(row.needs),
            desired_date=row.desired_date,
            status="nouvelle",
            created_at=now,
            updated_at=now,
        )
        req.events.append(
            RequestEvent(
                at=row.received_at,
                actor_user_id=ctx.user.id,
                kind="recue",
                to_status="nouvelle",
                detail="Import CSV",
            )
        )
        ctx.session.add(req)
        created += 1
    return created, updated
