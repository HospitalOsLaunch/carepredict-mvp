"""Explainable request prioritisation and site/date suggestion.

No machine learning here: a coordinator must be able to read why a request is
on top of the queue. Each factor is a number in [0, 1]; the score is their
weighted average on a 0-100 scale. Weights are configurable per group.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime

from services.admissions_smr.vocab import MENTIONS, SPECIAL_NEEDS

DEFAULT_WEIGHTS: Mapping[str, float] = {
    "disponibilite": 0.40,
    "attente": 0.25,
    "urgence": 0.20,
    "adresseur": 0.15,
}

FACTOR_LABELS: Mapping[str, str] = {
    "disponibilite": "Lit disponible à la date souhaitée",
    "attente": "Temps d'attente de la réponse",
    "urgence": "Date d'entrée souhaitée proche",
    "adresseur": "Adresseur régulier du groupe",
}

SAFE_PROBABILITY = 0.8
WAIT_SATURATION_HOURS = 48.0
REFERRER_SATURATION_SHARE = 0.2


@dataclass(frozen=True)
class RequestFeatures:
    request_id: int
    received_at: datetime
    mention: str
    care_level: int
    isolation_required: bool
    needs: frozenset[str]
    desired_date: date | None
    referrer_facility: str


@dataclass(frozen=True)
class DayAvailability:
    day: date
    free_expected: float
    prob_at_least_one_free: float


@dataclass(frozen=True)
class SiteCandidate:
    site_id: int
    site_name: str
    mentions: frozenset[str]
    capabilities: frozenset[str]
    isolation_rooms_by_mention: Mapping[str, int]
    availability_by_mention: Mapping[str, Sequence[DayAvailability]]
    referrer_share: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Factor:
    code: str
    label: str
    value: float
    weight: float
    contribution: float
    detail: str


@dataclass(frozen=True)
class SiteSuggestion:
    site_id: int
    site_name: str
    eligible: bool
    blockers: list[str]
    score: float
    factors: list[Factor]
    safe_date: date | None
    probable_date: date | None


@dataclass(frozen=True)
class Prioritisation:
    request_id: int
    score: float
    best: SiteSuggestion | None
    suggestions: list[SiteSuggestion]


def normalise_weights(raw: Mapping[str, float] | None) -> dict[str, float]:
    weights = dict(DEFAULT_WEIGHTS)
    for key, value in (raw or {}).items():
        if key in weights and value >= 0:
            weights[key] = float(value)
    total = sum(weights.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: v / total for k, v in weights.items()}


def _blockers(req: RequestFeatures, site: SiteCandidate) -> list[str]:
    blockers: list[str] = []
    if req.mention not in site.mentions:
        label = MENTIONS.get(req.mention, req.mention)
        blockers.append(f"Pas de lits en mention « {label} » sur ce site")
    missing = sorted(req.needs - site.capabilities)
    if missing:
        names = ", ".join(SPECIAL_NEEDS.get(code, code) for code in missing)
        blockers.append(f"Besoin non couvert : {names}")
    if req.isolation_required and site.isolation_rooms_by_mention.get(req.mention, 0) <= 0:
        blockers.append("Aucune chambre d'isolement dans cette mention")
    return blockers


def _dates(
    availability: Sequence[DayAvailability], target: date
) -> tuple[date | None, date | None]:
    safe = next(
        (
            d.day
            for d in availability
            if d.day >= target and d.prob_at_least_one_free >= SAFE_PROBABILITY
        ),
        None,
    )
    probable = next(
        (d.day for d in availability if d.day >= target and d.free_expected >= 1.0), None
    )
    return safe, probable


def suggest_for_site(
    req: RequestFeatures,
    site: SiteCandidate,
    today: date,
    now: datetime,
    weights: Mapping[str, float],
) -> SiteSuggestion:
    blockers = _blockers(req, site)
    target = max(today, req.desired_date or today)
    availability = site.availability_by_mention.get(req.mention, [])
    safe, probable = _dates(availability, target)
    horizon_days = max(1, len(availability))

    if safe is None and probable is None:
        dispo, dispo_detail = 0.0, "Aucun lit prévu sur l'horizon de prévision"
    else:
        best_day = safe or probable
        assert best_day is not None
        delay = (best_day - target).days
        dispo = max(0.0, 1.0 - delay / horizon_days)
        if safe is None:
            dispo *= 0.6
        when = "à la date souhaitée" if delay == 0 else f"{delay} j après la date souhaitée"
        certainty = "sûr" if safe is not None else "probable"
        dispo_detail = f"Lit {certainty} {when}"

    waited_h = max(0.0, (now - req.received_at).total_seconds() / 3600.0)
    attente = min(1.0, waited_h / WAIT_SATURATION_HOURS)
    attente_detail = f"Reçue il y a {_format_hours(waited_h)}"

    if req.desired_date is None:
        urgence, urgence_detail = 0.5, "Pas de date souhaitée"
    else:
        days_to = (req.desired_date - today).days
        if days_to <= 2:
            urgence = 1.0
        elif days_to <= 7:
            urgence = 0.5
        else:
            urgence = 0.2
        urgence_detail = f"Entrée souhaitée dans {max(0, days_to)} j"

    share = site.referrer_share.get(req.referrer_facility, 0.0)
    adresseur = min(1.0, share / REFERRER_SATURATION_SHARE)
    adresseur_detail = f"{round(share * 100)} % des admissions du site sur 12 mois"

    values = {
        "disponibilite": (dispo, dispo_detail),
        "attente": (attente, attente_detail),
        "urgence": (urgence, urgence_detail),
        "adresseur": (adresseur, adresseur_detail),
    }
    factors = [
        Factor(
            code=code,
            label=FACTOR_LABELS[code],
            value=round(value, 3),
            weight=round(weights[code], 3),
            contribution=round(100 * weights[code] * value, 1),
            detail=detail,
        )
        for code, (value, detail) in values.items()
    ]
    score = round(sum(f.contribution for f in factors), 1)
    return SiteSuggestion(
        site_id=site.site_id,
        site_name=site.site_name,
        eligible=not blockers,
        blockers=blockers,
        score=score if not blockers else 0.0,
        factors=factors,
        safe_date=safe if not blockers else None,
        probable_date=probable if not blockers else None,
    )


def prioritise(
    req: RequestFeatures,
    sites: Sequence[SiteCandidate],
    today: date,
    now: datetime,
    weights: Mapping[str, float] | None = None,
    preferred_site_id: int | None = None,
) -> Prioritisation:
    """Score every site for a request; the request's priority is its best eligible site.

    When the request is already assigned to a site (``preferred_site_id``), that
    site is the reference as long as it stays eligible.
    """
    w = normalise_weights(weights)
    suggestions = [suggest_for_site(req, s, today, now, w) for s in sites]
    suggestions.sort(key=lambda s: (not s.eligible, -s.score, s.site_name))
    eligible = [s for s in suggestions if s.eligible]
    best: SiteSuggestion | None = None
    if preferred_site_id is not None:
        best = next((s for s in eligible if s.site_id == preferred_site_id), None)
    if best is None and eligible:
        best = eligible[0]
    return Prioritisation(
        request_id=req.request_id,
        score=best.score if best else 0.0,
        best=best,
        suggestions=suggestions,
    )


def _format_hours(hours: float) -> str:
    if hours < 1:
        return f"{max(1, round(hours * 60))} min"
    if hours < 48:
        return f"{round(hours)} h"
    return f"{round(hours / 24)} j"
