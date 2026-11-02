"""ROR capacity export, ORU indicators and the simulated send queue (owner: ror-oru-export).

Nothing here talks to the ROR, to Inéa or to any third party: this module imports no HTTP
client and opens no socket. ``POST /ror/outbox`` only stores a snapshot with the status
``simulated``, so that the payload, its digest and who prepared it can be shown.

Roles: every read role reads the export and the ORU indicators within its site scope; only
``admin_groupe`` prepares a (simulated) send and edits the ROR settings of a unit.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select

from services.admissions_smr.api.deps import (
    UNPROCESSABLE,
    AdminCtx,
    AdminLateLockCtx,
    Ctx,
    ReadCtx,
    lock_tenant,
)
from services.admissions_smr.api.routes_beds import unit_label, unit_views, visible_sites
from services.admissions_smr.api.routes_ed import (
    as_declared,
    declarations_since,
    load_admitted,
    load_visits,
)
from services.admissions_smr.clock import local_time
from services.admissions_smr.domain import oru
from services.admissions_smr.domain.ed import (
    BOARDING_HOUR,
    STALE_AFTER,
    DayPoint,
    daily_series,
)
from services.admissions_smr.domain.forecast import StayRecord
from services.admissions_smr.domain.metrics import (
    CapacityPoint,
    PoolCapacity,
    daily_occupancy,
    pool_capacity,
)
from services.admissions_smr.domain.ror import (
    FORECAST_OFFSETS,
    FRESHNESS_SOURCES,
    MODE_EXPECTED,
    MODE_RELEASED,
    NO_FORECAST,
    TENSION_NORMAL_MIN,
    Code,
    ForecastPoint,
    ForecastSource,
    UnitExport,
    UnitSnapshot,
    unit_export,
)
from services.admissions_smr.domain.tension import DECLARATION_LEVELS
from services.admissions_smr.models import (
    AuditEntry,
    Bed,
    BedPool,
    CapacityChange,
    ForecastRun,
    ForecastValue,
    Movement,
    RorOutbox,
    Site,
    Stay,
    TensionDeclaration,
    User,
)
from services.admissions_smr.schemas_liscop import (
    OruDayOut,
    OruIndicatorsOut,
    RorCapaciteFhirOut,
    RorCapaciteOut,
    RorCode,
    RorExportOut,
    RorFermetureOut,
    RorFraicheurOut,
    RorGenreOut,
    RorOperationnelOut,
    RorOutboxOut,
    RorPrevisionNatureOut,
    RorPrevisionOut,
    RorPrevisionRunOut,
    RorReferentielOut,
    RorTensionOut,
    RorUniteOut,
    RorUnitSettingsIn,
    RorUnitSettingsOut,
)
from services.admissions_smr.service import build_forecast, group_sites, reservations, stay_records
from services.admissions_smr.vocab import FORECAST_STALE_AFTER_HOURS, SYNTHETIC_GROUPS

router = APIRouter()

WARNING = (
    "Maquette : rien n'est envoyé au ROR. Ce document montre ce que HospitalOS pourrait "
    "remonter automatiquement, à chaque mouvement, au ROR national et aux outils régionaux "
    "qui le lisent (LISCOP en Hauts-de-France)."
)

TERMINOLOGIES = "https://interop.esante.gouv.fr/terminologies"
REFERENCES = [
    RorReferentielOut(
        nom="JDV_J188_TypeStatutCapacite_ROR",
        url=f"{TERMINOLOGIES}/ValueSet-JDV-J188-TypeStatutCapacite-ROR.html",
    ),
    RorReferentielOut(
        nom="JDV_J189_TemporaliteCapacite_ROR",
        url=f"{TERMINOLOGIES}/ValueSet-JDV-J189-TemporaliteCapacite-ROR.html",
    ),
    RorReferentielOut(
        nom="JDV_J190_GenreCapacite_ROR (TRE_R332)",
        url=f"{TERMINOLOGIES}/CodeSystem-TRE-R332-GenreCapacite.html",
    ),
    RorReferentielOut(
        nom="JDV_J191_TypeFermetureCapacite_ROR",
        url=f"{TERMINOLOGIES}/ValueSet-JDV-J191-TypeFermetureCapacite-ROR.html",
    ),
    RorReferentielOut(
        nom="ROR FHIR IG : extension supported-capacity",
        url="https://interop.esante.gouv.fr/ig/fhir/ror/StructureDefinition-ror-location-supported-capacity-definitions.html",
    ),
    RorReferentielOut(
        nom="ANS : ROR, capacité en lits, indicateurs, définitions v1.0.1",
        url="https://esante.gouv.fr/sites/default/files/media/document/ROR_Capacite-En-Lits_Indicateurs_Definitions_VFD_v1.0.1.pdf",
    ),
]

ASSUMPTIONS = [
    "Disponibles (J188 02) : lits utilisables du plan des lits (libres, acceptant au moins un "
    "sexe, ni bloqués, ni réservés, ni à nettoyer). Sans plan des lits : lits ouverts − "
    "présents − admissions accordées pour aujourd'hui ou demain.",
    "Genre (J190) : femme 01, homme 02, indéterminé 04 (une femme ou un homme peut y être "
    "placé) ; les trois s'additionnent pour donner les disponibles.",
    "Type de fermeture (J191) déduit du motif : manque de personnel et fermeture saisonnière "
    "→ réactivable ; travaux → non réactivable ; lit bloqué ou autre motif → indéterminé. "
    "Correspondance à valider.",
    "Opérationnel (LISCOP) : en service = installés − fermés ; réactivables = fermetures de "
    "type 01 ; supplémentaires = lits supplémentaires déclarés (J188 06).",
    "Réservés crise / SSE : nombre déclaré sur l'unité, hors disponibles.",
    "Prévisionnel J+1, J+2, J+7 (J189 03, 04, 05) : « disponibles attendus » du moteur de "
    "prévision (moyenne, fourchette à 80 %, probabilités de tension et de critique). À "
    "défaut, « libérés non promis » d'après la seule prévision des sorties, signalé comme "
    "tel et jamais transmis comme disponibilité ROR.",
    f"Tension : normal si au moins {TENSION_NORMAL_MIN:.0%} des lits installés sont "
    "disponibles, critique à 0, tension entre les deux (légende LISCOP, à confirmer).",
    "Fraîcheur : dernier mouvement reçu, changement de statut de lit, changement de capacité "
    "ou séjour saisi, le plus récent des quatre.",
]

NOT_RECORDED = [
    "Identifiant ROR de chaque unité (à demander à Inéa ou à lire dans le ROR).",
    "Type de source de la capacité (J193), type de lit supplémentaire (J192), type de crise "
    "(J194), affectation temporaire (J195) : codes à vérifier avant de les remplir.",
    "Habilitation et canal d'alimentation (EAI régional d'Inéa ou ROR national directement).",
]

ORU_DEFINITIONS = [
    "Passages : arrivées aux urgences dans la journée (heure de Paris).",
    "Présents, en attente de lit, lits brancards et hébergés : lus à 10 h (définitions de la "
    "page Urgences). Une déclaration manuelle du jour remplace le calcul ; la colonne "
    "« calculé » garde la valeur calculée.",
    "Unités en tension ou critiques : lits ouverts (historique des capacités) − patients "
    "présents en fin de journée, légende LISCOP. Approximation : réservations, lits bloqués "
    "et genre n'ont pas d'historique.",
    "HET et Plan blanc : déclaration active à un moment de la journée (site ou établissement).",
    "Prévision des lits brancards à 10 h : dernière prévision stockée couvrant le jour.",
]

FORECAST_AHEAD = 7  # the ORU period may end up to J+7 to include the forecast
LEVEL_LABELS = {k: v for levels in DECLARATION_LEVELS.values() for k, v in levels.items()}
# ROR unit identifier: letters, digits and . _ : - (format to confirm with Inéa).
ROR_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")


# --- loading ------------------------------------------------------------------------------


def latest_run(ctx: Ctx) -> ForecastRun | None:
    return ctx.session.scalars(
        select(ForecastRun)
        .where(ForecastRun.group_id == ctx.group.id, ForecastRun.status == "ok")
        .order_by(ForecastRun.created_at.desc(), ForecastRun.id.desc())
        .limit(1)
    ).first()


def stored_forecasts(
    ctx: Ctx, run: ForecastRun, pool_ids: list[int], today: date
) -> dict[int, ForecastSource]:
    days = [today + timedelta(days=k) for k in FORECAST_OFFSETS]
    rows = ctx.session.scalars(
        select(ForecastValue).where(
            ForecastValue.run_id == run.id,
            ForecastValue.scope == "unit",
            ForecastValue.target == "available_beds",
            ForecastValue.pool_id.in_(pool_ids),
            ForecastValue.day.in_(days),
        )
    )
    points: dict[int, list[ForecastPoint]] = defaultdict(list)
    for r in rows:
        assert r.pool_id is not None
        points[r.pool_id].append(
            ForecastPoint(r.day, r.mean, r.q10, r.q90, r.p_tension, r.p_critique)
        )
    return {
        pid: ForecastSource(MODE_EXPECTED, pts, run.model_version, run.as_of, run.created_at)
        for pid, pts in points.items()
    }


def closure_reasons(ctx: Ctx, sites: Sequence[Site], today: date) -> dict[tuple[int, str], str]:
    current = [
        PoolCapacity(s.id, p.mention, p.beds_installed, p.beds_open) for s in sites for p in s.pools
    ]
    caps = pool_capacity(capacity_points(ctx, [s.id for s in sites]), current, today, today)
    return {key: series[today][2] for key, series in caps.items()}


def capacity_points(ctx: Ctx, site_ids: list[int]) -> list[CapacityPoint]:
    return [
        CapacityPoint(
            c.site_id, c.mention, c.effective_date, c.beds_installed, c.beds_open, c.reason
        )
        for c in ctx.session.scalars(
            select(CapacityChange).where(
                CapacityChange.group_id == ctx.group.id, CapacityChange.site_id.in_(site_ids)
            )
        )
    ]


def latest_changes(ctx: Ctx, sites: Sequence[Site]) -> dict[int, dict[str, datetime | None]]:
    """Per pool: the latest movement applied, bed change, capacity change and manual entry."""
    site_ids = [s.id for s in sites]
    pool_of = {(s.id, p.mention): p.id for s in sites for p in s.pools}
    out: dict[int, dict[str, datetime | None]] = defaultdict(dict)

    def keep(pool_id: int | None, source: str, at: datetime | None) -> None:
        if pool_id is None or at is None:
            return
        known = out[pool_id].get(source)
        if known is None or at > known:
            out[pool_id][source] = at

    for pid, at in ctx.session.execute(
        select(Movement.pool_id, func.max(Movement.received_at))
        .where(
            Movement.group_id == ctx.group.id,
            Movement.site_id.in_(site_ids),
            Movement.status == "applied",
        )
        .group_by(Movement.pool_id)
    ):
        keep(pid, "mouvement", at)
    for pid, at in ctx.session.execute(
        select(Bed.pool_id, func.max(Bed.updated_at))
        .where(Bed.group_id == ctx.group.id, Bed.site_id.in_(site_ids))
        .group_by(Bed.pool_id)
    ):
        keep(pid, "lit", at)
    for site_id, mention, at in ctx.session.execute(
        select(CapacityChange.site_id, CapacityChange.mention, func.max(CapacityChange.created_at))
        .where(CapacityChange.group_id == ctx.group.id, CapacityChange.site_id.in_(site_ids))
        .group_by(CapacityChange.site_id, CapacityChange.mention)
    ):
        keep(pool_of.get((site_id, mention)), "capacite", at)
    for s in sites:
        for p in s.pools:
            keep(p.id, "capacite", p.updated_at)
    for site_id, mention, at in ctx.session.execute(
        select(Stay.site_id, Stay.mention, func.max(Stay.updated_at))
        .where(
            Stay.group_id == ctx.group.id,
            Stay.site_id.in_(site_ids),
            Stay.source.in_(("saisie", "import")),
        )
        .group_by(Stay.site_id, Stay.mention)
    ):
        keep(pool_of.get((site_id, mention)), "saisie", at)
    return out


def build_units(ctx: Ctx, sites: Sequence[Site], run: ForecastRun | None) -> list[UnitExport]:
    today = ctx.clock.today()
    views = {v.pool.id: v for v in unit_views(ctx.session, ctx.group.id, sites)}
    pools = [(s, p) for s in sites for p in s.pools if p.beds_installed > 0 or p.id in views]
    stored = stored_forecasts(ctx, run, [p.id for _, p in pools], today) if run else {}
    # The discharge model is costly: only fitted when a unit needs it.
    needs_fallback = any(p.id not in stored or p.id not in views for _, p in pools)
    fc = (
        build_forecast(ctx.session, ctx.group.id, list(sites), today, max(FORECAST_OFFSETS) + 1)
        if needs_fallback
        else None
    )
    promised = reservations(ctx.session, ctx.group.id) if needs_fallback else {}
    reasons = closure_reasons(ctx, sites, today)
    changes = latest_changes(ctx, sites)
    tomorrow = today + timedelta(days=1)

    units: list[UnitExport] = []
    for site, pool in pools:
        key = (site.id, pool.mention)
        pf = fc.pools.get(key) if fc else None
        forecast = stored.get(pool.id)
        if forecast is None and pf is not None:
            forecast = ForecastSource(
                MODE_RELEASED,
                [ForecastPoint(d.day, d.free_expected, d.free_p10, d.free_p90) for d in pf.days],
                "Prévision des sorties (durées de séjour)",
                today,
                None,
            )
        view = views.get(pool.id)
        snapshot = UnitSnapshot(
            site_id=site.id,
            site_name=site.name,
            finess=site.finess,
            pool_id=pool.id,
            code=pool.mention,
            label=unit_label(pool),
            unit_type=pool.unit_type,
            discipline=pool.discipline,
            ror_unit_id=pool.ror_unit_id,
            beds_installed=pool.beds_installed,
            beds_open=pool.beds_open,
            extra_beds=pool.extra_beds,
            crisis_reserved_beds=pool.crisis_reserved_beds,
            closure_reason=reasons.get(key, "autre"),
            availability=view.availability if view else None,
            occupied=pf.occupied_now if pf else 0,
            reserved_24h=sum(n for d, n in promised.get(key, {}).items() if d <= tomorrow),
            forecast=forecast or NO_FORECAST,
            changes=changes.get(pool.id, {}),
        )
        units.append(unit_export(snapshot, today))
    return units


# --- serialisation ------------------------------------------------------------------------


def code(c: Code | None) -> RorCode | None:
    return None if c is None else RorCode(code=c[0], libelle=c[1])


def unit_out(u: UnitExport, now: datetime) -> RorUniteOut:
    f = u.freshness
    g = u.gender
    return RorUniteOut(
        site_id=u.site_id,
        etablissement=u.site_name,
        finess_geographique=u.finess,
        pool_id=u.pool_id,
        identifiant_unite_ror=u.ror_unit_id,
        mention=u.code,
        libelle_unite=u.label,
        type_unite=u.unit_type,
        discipline=u.discipline,
        capacites=[
            RorCapaciteOut(
                statut=RorCode(code=c.code, libelle=c.label), nombre=c.count, remarque=c.note
            )
            for c in u.capacities
        ],
        fermetures=[
            RorFermetureOut(
                type_fermeture=RorCode(code=c.code, libelle=c.label),
                nombre=c.count,
                motif_interne=c.internal_reason,
            )
            for c in u.closures
        ],
        disponibles_par_genre=RorGenreOut(
            femme=g.female,
            homme=g.male,
            indetermine=g.undetermined,
            total=g.total,
            isolement=g.isolation,
            niveau="lit" if g.level == "lit" else "unite",
        ),
        operationnel=RorOperationnelOut(
            en_service=u.operational.in_service,
            reactivables=u.operational.reactivable,
            supplementaires=u.operational.extra,
        ),
        reserves_crise_sse=u.crisis_reserved,
        previsionnel=[
            RorPrevisionOut(
                echeance=line.horizon,
                date=line.day,
                temporalite=RorCode(code=line.temporality[0], libelle=line.temporality[1]),
                moyenne=line.mean,
                fourchette_80=(line.low, line.high),
                p_tension=line.p_tension,
                p_critique=line.p_critique,
            )
            for line in u.forecast.lines
        ],
        previsionnel_nature=RorPrevisionNatureOut(
            nature=u.forecast.mode,  # type: ignore[arg-type]
            libelle=u.forecast.label,
            modele=u.forecast.model,
            date_de_calcul=u.forecast.as_of,
            calcule_le=u.forecast.computed_at,
        ),
        tension=RorTensionOut(
            niveau=u.tension.level,  # type: ignore[arg-type]
            taux_disponibilite=u.tension.availability_rate,
        ),
        fraicheur=None
        if f is None
        else RorFraicheurOut(
            le=f.at,
            source=f.source,
            libelle=FRESHNESS_SOURCES[f.source],
            age_heures=round(max(0.0, (now - f.at).total_seconds() / 3600), 2),
        ),
        dernier_mouvement_saisi=f.at if f else None,
        ror_capacites=[
            RorCapaciteFhirOut(
                capacityType=RorCode(code=r.nature[0], libelle=r.nature[1]),
                capacityStatus=RorCode(code=r.status[0], libelle=r.status[1]),
                temporalityCapacity=RorCode(code=r.temporality[0], libelle=r.temporality[1]),
                nbCapacity=r.count,
                genderCapacityAvailable=code(r.gender),
                capacityClosingType=code(r.closing_type),
                capacityUpdateDate=r.update_date,
            )
            for r in u.records
        ],
        a_completer=u.missing,
    )


def export_out(ctx: Ctx, sites: Sequence[Site]) -> RorExportOut:
    now, today = ctx.clock.now(), ctx.clock.today()
    run = latest_run(ctx)
    units = build_units(ctx, sites, run)
    return RorExportOut(
        avertissement=WARNING,
        emetteur=f"HospitalOS — {ctx.group.name} (maquette)",
        genere_le=now,
        date_situation=today,
        synthetique=ctx.group.name in SYNTHETIC_GROUPS,
        prevision=None
        if run is None
        else RorPrevisionRunOut(
            id=run.id,
            date_de_calcul=run.as_of,
            calcule_le=run.created_at,
            modele=run.model_version,
            perimee=run.as_of != today
            or (now - run.created_at).total_seconds() > FORECAST_STALE_AFTER_HOURS * 3600,
        ),
        referentiels=REFERENCES,
        hypotheses=ASSUMPTIONS,
        non_suivi_dans_le_pilote=NOT_RECORDED,
        unites=[unit_out(u, now) for u in units],
    )


# --- ROR export ---------------------------------------------------------------------------


@router.get("/ror/export", response_model=RorExportOut, tags=["ror"])
def ror_export(ctx: ReadCtx, site_id: int | None = None) -> RorExportOut:
    return export_out(ctx, visible_sites(ctx, site_id))


def outbox_out(row: RorOutbox, by: str | None, content: RorExportOut | None) -> RorOutboxOut:
    units = len(json.loads(row.payload_json).get("unites", []))
    return RorOutboxOut(
        id=row.id,
        cree_le=row.created_at,
        type=row.kind,
        statut=row.status,
        empreinte_sha256=row.digest,
        unites=units,
        prepare_par=by,
        contenu=content,
    )


@router.post("/ror/outbox", response_model=RorOutboxOut, status_code=201, tags=["ror"])
def prepare_send(ctx: AdminLateLockCtx) -> RorOutboxOut:
    """Stores the current export as a simulated send. Never sends anything.

    The export (the discharge model may be fitted) is built in a read transaction; the
    tenant write lock is taken only for the insert and its audit entry (C-8).
    """
    content = export_out(ctx, group_sites(ctx))
    payload = json.dumps(
        content.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    ctx.session.rollback()  # end the read transaction; nothing was written
    ctx.group = lock_tenant(ctx.session, ctx.group.id)
    row = RorOutbox(
        group_id=ctx.group.id,
        created_at=ctx.clock.now(),
        kind="ror_capacity",
        payload_json=payload,
        digest=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        status="simulated",
    )
    ctx.session.add(row)
    ctx.session.flush()
    ctx.audit(
        "ror.envoi_simule",
        "ror_outbox",
        row.id,
        f"{len(content.unites)} unités, sha256 {row.digest[:12]}, aucun envoi",
    )
    ctx.session.commit()
    return outbox_out(row, ctx.user.full_name, content)


@router.get("/ror/outbox", response_model=list[RorOutboxOut], tags=["ror"])
def send_history(ctx: AdminCtx) -> list[RorOutboxOut]:
    rows = list(
        ctx.session.scalars(
            select(RorOutbox)
            .where(RorOutbox.group_id == ctx.group.id)
            .order_by(RorOutbox.created_at.desc(), RorOutbox.id.desc())
            .limit(50)
        )
    )
    authors = dict(
        ctx.session.execute(
            select(AuditEntry.entity_id, User.full_name)
            .join(User, User.id == AuditEntry.user_id)
            .where(
                AuditEntry.group_id == ctx.group.id,
                AuditEntry.entity == "ror_outbox",
                AuditEntry.entity_id.in_([str(r.id) for r in rows]),
            )
        ).all()
    )
    return [outbox_out(r, authors.get(str(r.id)), None) for r in rows]


@router.put("/ror/units/{pool_id}", response_model=RorUnitSettingsOut, tags=["ror"])
def set_unit_settings(pool_id: int, body: RorUnitSettingsIn, ctx: AdminCtx) -> RorUnitSettingsOut:
    pool = ctx.session.get(BedPool, pool_id)
    site = ctx.session.get(Site, pool.site_id) if pool else None
    if pool is None or site is None or site.group_id != ctx.group.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unité introuvable")
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(UNPROCESSABLE, "Rien à modifier")
    if "ror_unit_id" in changes:
        ror_id = (body.ror_unit_id or "").strip() or None
        if ror_id is not None and not ROR_ID.fullmatch(ror_id):
            raise HTTPException(
                UNPROCESSABLE,
                "Identifiant ROR invalide : lettres, chiffres et . _ : - (64 caractères au plus)",
            )
        pool.ror_unit_id = ror_id
    for name in ("extra_beds", "crisis_reserved_beds"):
        if name in changes:
            if changes[name] is None:
                raise HTTPException(UNPROCESSABLE, f"{name} : indiquez un nombre")
            setattr(pool, name, changes[name])
    if pool.crisis_reserved_beds > pool.beds_installed + pool.extra_beds:
        raise HTTPException(
            UNPROCESSABLE,
            "Réservés crise / SSE : pas plus que les lits installés et supplémentaires",
        )
    pool.updated_at = ctx.clock.now()
    detail = ", ".join(f"{k} = {getattr(pool, k)}" for k in changes)
    ctx.audit("ror.unite", "bed_pool", pool.id, detail)
    ctx.session.commit()
    return RorUnitSettingsOut(
        pool_id=pool.id,
        ror_unit_id=pool.ror_unit_id,
        extra_beds=pool.extra_beds,
        crisis_reserved_beds=pool.crisis_reserved_beds,
    )


# --- ORU indicators -----------------------------------------------------------------------


def oru_rows(ctx: Ctx, sites: Sequence[Site], start: date, end: date) -> list[oru.OruDay]:
    zone, now, today = ctx.clock.zone, ctx.clock.now(), ctx.clock.today()
    days = oru.days_between(start, end)
    # 10:00 readings exist up to today once 10:00 has passed, else up to yesterday.
    last_read = today if now >= local_time(today, BOARDING_HOUR, zone) else today - timedelta(1)
    read_days = [d for d in days if d <= last_read]
    site_ids = [s.id for s in sites]

    # Units: end-of-day census against the dated capacity.
    current = [
        PoolCapacity(s.id, p.mention, p.beds_installed, p.beds_open) for s in sites for p in s.pools
    ]
    caps = pool_capacity(capacity_points(ctx, site_ids), current, start, end)
    stays: dict[tuple[int, str], list[StayRecord]] = defaultdict(list)
    for r in stay_records(ctx.session, ctx.group.id, site_ids):
        stays[(r.site_id, r.mention)].append(r)
    occupancy = {key: daily_occupancy(stays.get(key, []), start, min(end, today)) for key in caps}

    declarations = [
        (d.site_id, oru.Declaration(d.kind, d.level, d.started_at, d.ended_at))
        for d in ctx.session.scalars(
            select(TensionDeclaration).where(
                TensionDeclaration.group_id == ctx.group.id,
                TensionDeclaration.started_at < local_time(end + timedelta(1), time(0), zone),
            )
        )
    ]

    run = latest_run(ctx)
    forecasts: dict[tuple[int, date], oru.BoardingForecast] = {}
    if run is not None:
        for v in ctx.session.scalars(
            select(ForecastValue).where(
                ForecastValue.run_id == run.id,
                ForecastValue.scope == "site",
                ForecastValue.target == "boarding_10h",
                ForecastValue.site_id.in_(site_ids),
                ForecastValue.day >= start,
                ForecastValue.day <= end,
            )
        ):
            assert v.site_id is not None
            forecasts[(v.site_id, v.day)] = oru.BoardingForecast(v.mean, v.q10, v.q90, run.as_of)

    rows: list[oru.OruDay] = []
    for site in sites:
        has_ed = any(p.unit_type == "urgences" for p in site.pools)
        ed_points: dict[date, DayPoint] = {}
        arrivals: dict[date, int] = {}
        if has_ed:
            since = local_time(start, time(0), zone) - STALE_AFTER
            visits = load_visits(ctx, site.id, since)
            arrivals = oru.arrivals_by_day((v.arrived_at for v in visits), zone)
            if read_days:
                points = daily_series(
                    visits,
                    load_admitted(ctx, site.id, since),
                    read_days,
                    zone,
                    as_declared(declarations_since(ctx, site.id, local_time(start, time(0), zone))),
                )
                ed_points = {p.day: p for p in points}
        mine = [d for sid, d in declarations if sid is None or sid == site.id]
        keys = [(site.id, p.mention) for p in site.pools]
        for day in days:
            levels = (
                oru.count_levels(
                    oru.unit_levels(occupancy[k], caps[k], day) for k in keys if k in caps
                )
                if day <= today
                else None
            )
            rows.append(
                oru.oru_day(
                    site.id,
                    site.name,
                    day,
                    today,
                    ed_points.get(day),
                    arrivals.get(day, 0) if has_ed and day <= today else None,
                    levels,
                    oru.active_declarations(mine, day, zone) if day <= today else {},
                    forecasts.get((site.id, day)),
                )
            )
    rows.sort(key=lambda r: (r.day, r.site_name))
    return rows


@router.get(
    "/oru/indicators",
    response_model=OruIndicatorsOut,
    responses={200: {"content": {"text/csv": {}}}},
    tags=["ror"],
)
def oru_indicators(
    ctx: ReadCtx,
    start: date,
    end: date,
    site_id: int | None = None,
    format: Literal["json", "csv"] = Query("json"),
) -> OruIndicatorsOut | Response:
    today = ctx.clock.today()
    if start > end:
        raise HTTPException(UNPROCESSABLE, "La date de début est après la date de fin")
    if (end - start).days + 1 > oru.MAX_DAYS:
        raise HTTPException(UNPROCESSABLE, f"Période de {oru.MAX_DAYS} jours au plus")
    if end > today + timedelta(days=FORECAST_AHEAD):
        raise HTTPException(UNPROCESSABLE, f"Fin au plus tard à J+{FORECAST_AHEAD}")
    rows = oru_rows(ctx, visible_sites(ctx, site_id), start, end)
    if format == "csv":
        return Response(
            content=oru.to_csv(rows, LEVEL_LABELS).encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="oru-indicateurs-{start}-{end}.csv"'
            },
        )
    return OruIndicatorsOut(
        start=start,
        end=end,
        generated_at=ctx.clock.now(),
        synthetic=ctx.group.name in SYNTHETIC_GROUPS,
        definitions=ORU_DEFINITIONS,
        days=[OruDayOut(**r.__dict__) for r in rows],
    )
