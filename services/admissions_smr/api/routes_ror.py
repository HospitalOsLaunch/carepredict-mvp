"""Mock-up of a ROR capacity export. Read only: nothing is ever sent to the ROR."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from services.admissions_smr.api.deps import ReadCtx
from services.admissions_smr.domain.metrics import CapacityPoint, PoolCapacity, pool_capacity
from services.admissions_smr.domain.ror import (
    FORECAST_OFFSETS,
    NOT_RECORDED,
    TENSION_NORMAL_MIN,
    ForecastDay,
    PoolSnapshot,
    UnitExport,
    unit_export,
)
from services.admissions_smr.models import CapacityChange, Stay
from services.admissions_smr.schemas import (
    RorCapaciteOut,
    RorCode,
    RorExportOut,
    RorFermetureOut,
    RorPrevisionOut,
    RorReferentielOut,
    RorTensionOut,
    RorUniteOut,
)
from services.admissions_smr.service import build_forecast, get_site, group_sites, reservations
from services.admissions_smr.vocab import MENTIONS

router = APIRouter()

WARNING = (
    "Maquette : rien n'est envoyé au ROR. Ce document montre ce que HospitalOS pourrait "
    "remonter automatiquement, à chaque saisie, pour alimenter le ROR national et les "
    "outils régionaux qui le lisent (LISCOP en Hauts-de-France)."
)

REFERENCES = [
    RorReferentielOut(
        nom="JDV_J188_TypeStatutCapacite_ROR",
        url="https://interop.esante.gouv.fr/terminologies/1.4.0/ValueSet-JDV-J188-TypeStatutCapacite-ROR.html",
    ),
    RorReferentielOut(
        nom="JDV_J191_TypeFermetureCapacite_ROR",
        url="https://interop.esante.gouv.fr/terminologies/ValueSet-JDV-J191-TypeFermetureCapacite-ROR.html",
    ),
]

ASSUMPTIONS = [
    "Lits disponibles = lits ouverts − patients présents − admissions accordées pour "
    "aujourd'hui ou demain ; un lit ouvert est supposé doté du personnel nécessaire.",
    "Type de fermeture déduit du motif saisi : manque de personnel et fermeture "
    "saisonnière → réactivable ; travaux → non réactivable ; autre → indéterminé. "
    "Correspondance à valider.",
    "Prévisionnel J+1, J+2, J+7 : lits libres attendus d'après la prévision des sorties, "
    "avec la fourchette à 80 %. Ce bloc n'est pas un statut ROR ; il reprend les colonnes "
    "affichées par LISCOP.",
    f"Niveau de tension : normal si au moins {TENSION_NORMAL_MIN:.0%} des lits installés "
    "sont disponibles, critique à 0, tension entre les deux (légende LISCOP, à confirmer).",
]


def _last_movements(ctx: ReadCtx, site_ids: list[int]) -> dict[tuple[int, str], datetime]:
    """Latest entry that changed a pool: a stay created or edited, or a capacity change."""
    out: dict[tuple[int, str], datetime] = {}

    def keep(key: tuple[int, str], at: datetime | None) -> None:
        if at is not None and (key not in out or at > out[key]):
            out[key] = at

    stays = ctx.session.execute(
        select(Stay.site_id, Stay.mention, func.max(Stay.updated_at))
        .where(Stay.group_id == ctx.group.id, Stay.site_id.in_(site_ids))
        .group_by(Stay.site_id, Stay.mention)
    )
    for site_id, mention, at in stays:
        keep((site_id, mention), at)
    changes = ctx.session.execute(
        select(CapacityChange.site_id, CapacityChange.mention, func.max(CapacityChange.created_at))
        .where(CapacityChange.group_id == ctx.group.id, CapacityChange.site_id.in_(site_ids))
        .group_by(CapacityChange.site_id, CapacityChange.mention)
    )
    for site_id, mention, at in changes:
        keep((site_id, mention), at)
    return out


def _closure_reasons(ctx: ReadCtx, site_ids: list[int], today: date) -> dict[tuple[int, str], str]:
    sites = [s for s in group_sites(ctx) if s.id in site_ids]
    current = [
        PoolCapacity(s.id, p.mention, p.beds_installed, p.beds_open) for s in sites for p in s.pools
    ]
    changes = [
        CapacityPoint(
            c.site_id, c.mention, c.effective_date, c.beds_installed, c.beds_open, c.reason
        )
        for c in ctx.session.scalars(
            select(CapacityChange).where(
                CapacityChange.group_id == ctx.group.id, CapacityChange.site_id.in_(site_ids)
            )
        )
    ]
    caps = pool_capacity(changes, current, today, today)
    return {key: series[today][2] for key, series in caps.items()}


def _unit_out(unit: UnitExport) -> RorUniteOut:
    return RorUniteOut(
        site_id=unit.site_id,
        etablissement=unit.site_name,
        finess_geographique=unit.finess,
        identifiant_unite_ror=unit.ror_unit_id,
        mention=unit.mention,
        libelle_unite=unit.unit_label,
        capacites=[
            RorCapaciteOut(
                statut=RorCode(code=c.code, libelle=c.label), nombre=c.count, remarque=c.note
            )
            for c in unit.capacities
        ],
        fermetures=[
            RorFermetureOut(
                type_fermeture=RorCode(code=f.code, libelle=f.label),
                nombre=f.count,
                motif_interne=f.internal_reason,
            )
            for f in unit.closures
        ],
        previsionnel=[
            RorPrevisionOut(
                echeance=f.horizon,
                date=f.day,
                lits_disponibles_attendus=f.free_expected,
                fourchette_80=(f.free_low, f.free_high),
            )
            for f in unit.forecast
        ],
        tension=RorTensionOut(
            niveau=unit.tension.level, taux_disponibilite=unit.tension.availability_rate
        ),
        dernier_mouvement_saisi=unit.last_movement_at,
        a_completer=unit.missing,
    )


@router.get("/ror/export", response_model=RorExportOut, tags=["ror"])
def ror_export(ctx: ReadCtx, site_id: int | None = None) -> RorExportOut:
    sites = group_sites(ctx)
    if site_id is not None:
        get_site(ctx, site_id)
        if not ctx.can_see_site(site_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Site hors de votre périmètre")
        sites = [s for s in sites if s.id == site_id]
    today = ctx.clock.today()
    site_ids = [s.id for s in sites]
    # The forecast's first day is today, so J+7 needs eight days.
    fc = build_forecast(ctx.session, ctx.group.id, sites, today, max(FORECAST_OFFSETS) + 1)
    promised = reservations(ctx.session, ctx.group.id)
    reasons = _closure_reasons(ctx, site_ids, today)
    movements = _last_movements(ctx, site_ids)
    tomorrow = today + timedelta(days=1)

    units: list[RorUniteOut] = []
    for site in sites:
        for pool in site.pools:
            key = (site.id, pool.mention)
            pf = fc.pools.get(key)
            if pf is None:
                continue
            reserved_24h = sum(n for d, n in promised.get(key, {}).items() if d <= tomorrow)
            snapshot = PoolSnapshot(
                site_id=site.id,
                site_name=site.name,
                finess=site.finess,
                mention=pool.mention,
                mention_label=MENTIONS.get(pool.mention, pool.mention),
                beds_installed=pool.beds_installed,
                beds_open=pool.beds_open,
                closure_reason=reasons.get(key, "autre"),
                occupied=pf.occupied_now,
                reserved_24h=reserved_24h,
                forecast=[
                    ForecastDay(d.day, d.free_expected, d.free_p10, d.free_p90) for d in pf.days
                ],
                last_movement_at=movements.get(key),
            )
            units.append(_unit_out(unit_export(snapshot, today)))

    return RorExportOut(
        avertissement=WARNING,
        emetteur=f"HospitalOS — {ctx.group.name} (maquette)",
        genere_le=ctx.clock.now(),
        date_situation=today,
        referentiels=REFERENCES,
        hypotheses=ASSUMPTIONS,
        non_suivi_dans_le_pilote=list(NOT_RECORDED),
        unites=units,
    )
