"""Mock-up of what HospitalOS could send to the national ROR, for each bed pool.

Nothing here talks to the ROR. The module turns what the pilot already knows (beds
installed and open, patients present, promised admissions, the discharge forecast) into
the capacity vocabulary of the ROR, so that the export can be shown and discussed with
the regional teams that read it (LISCOP in Hauts-de-France).

Vocabularies used (ANS terminologies):

- JDV_J188_TypeStatutCapacite_ROR: installé, disponible, occupé, réservé, fermé,
  supplémentaire.
- JDV_J191_TypeFermetureCapacite_ROR: réactivable, non réactivable, indéterminé.

Two parts are proposals that still need validating with the ANS and the regional teams:
the mapping of our internal closure reasons to J191, and the forecast block (J+1, J+2,
J+7), which LISCOP displays but which is not one of the J188 statuses.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime

# The LISCOP tension legend lives in domain.tension; re-exported for existing callers.
from services.admissions_smr.domain.tension import TENSION_NORMAL_MIN as TENSION_NORMAL_MIN
from services.admissions_smr.domain.tension import Tension as Tension
from services.admissions_smr.domain.tension import tension_of as tension_of

# --- ANS vocabularies -------------------------------------------------------------------

STATUS_INSTALLED = ("01", "Installé")
STATUS_AVAILABLE = ("02", "Disponible")
STATUS_OCCUPIED = ("03", "Occupé")
STATUS_RESERVED = ("04", "Réservé")
STATUS_CLOSED = ("05", "Fermé")
STATUS_EXTRA = ("06", "Supplémentaire")

CLOSURE_REACTIVABLE = ("01", "Réactivable")
CLOSURE_NOT_REACTIVABLE = ("02", "Non réactivable")
CLOSURE_UNDETERMINED = ("03", "Indéterminé")

# Proposed mapping of the pilot's closure reasons (vocab.CAPACITY_REASONS) to J191.
# Staffing and seasonal closures can be reopened when needed; works cannot. To validate.
CLOSURE_TYPE_BY_REASON: dict[str, tuple[str, str]] = {
    "personnel": CLOSURE_REACTIVABLE,
    "saisonnier": CLOSURE_REACTIVABLE,
    "travaux": CLOSURE_NOT_REACTIVABLE,
}

# Forecast horizons shown by LISCOP next to the capacity: day offsets from today.
FORECAST_OFFSETS: tuple[int, ...] = (1, 2, 7)

# Fields the ROR knows that the pilot does not record yet.
NOT_RECORDED: tuple[str, ...] = (
    "Disponibilité par genre (femme, homme, indifférencié) : le sexe attendu des lits "
    "n'est pas suivi dans le pilote.",
    "Capacité supplémentaire (statut 06) : les lits supplémentaires ouverts en tension "
    "ne sont pas saisis.",
    "Identifiant ROR de l'unité : à rattacher pour chaque unité.",
)


@dataclass(frozen=True)
class ForecastDay:
    """Free beds expected on a day, with the 80 % range of the discharge forecast."""

    day: date
    free_expected: float
    free_p10: int
    free_p90: int


@dataclass(frozen=True)
class PoolSnapshot:
    site_id: int
    site_name: str
    finess: str | None
    mention: str
    mention_label: str
    beds_installed: int
    beds_open: int
    closure_reason: str
    occupied: int
    reserved_24h: int
    forecast: Sequence[ForecastDay]
    last_movement_at: datetime | None


@dataclass(frozen=True)
class CapacityLine:
    code: str
    label: str
    count: int | None
    note: str | None = None


@dataclass(frozen=True)
class ClosureLine:
    code: str
    label: str
    count: int
    internal_reason: str


@dataclass(frozen=True)
class ForecastLine:
    horizon: str
    day: date
    free_expected: float
    free_low: int
    free_high: int


@dataclass(frozen=True)
class UnitExport:
    site_id: int
    site_name: str
    finess: str | None
    ror_unit_id: str | None
    mention: str
    unit_label: str
    capacities: list[CapacityLine]
    closures: list[ClosureLine]
    forecast: list[ForecastLine]
    tension: Tension
    last_movement_at: datetime | None
    missing: list[str] = field(default_factory=list)


def closure_type(reason: str) -> tuple[str, str]:
    return CLOSURE_TYPE_BY_REASON.get(reason, CLOSURE_UNDETERMINED)


def available_beds(beds_open: int, occupied: int, reserved_24h: int) -> int:
    """J188 "disponible": a patient can be placed now, with staff, and the bed is not
    promised to an identified patient within 24 hours. Open beds are taken as staffed."""
    return max(0, beds_open - occupied - reserved_24h)


def unit_export(pool: PoolSnapshot, as_of: date) -> UnitExport:
    closed = max(0, pool.beds_installed - pool.beds_open)
    available = available_beds(pool.beds_open, pool.occupied, pool.reserved_24h)
    capacities = [
        CapacityLine(*STATUS_INSTALLED, pool.beds_installed),
        CapacityLine(*STATUS_AVAILABLE, available),
        CapacityLine(*STATUS_OCCUPIED, pool.occupied),
        CapacityLine(
            *STATUS_RESERVED,
            pool.reserved_24h,
            "Admissions déjà accordées pour aujourd'hui ou demain.",
        ),
        CapacityLine(*STATUS_CLOSED, closed),
        CapacityLine(*STATUS_EXTRA, None, "Non suivi dans le pilote."),
    ]
    closures = (
        [ClosureLine(*closure_type(pool.closure_reason), closed, pool.closure_reason)]
        if closed
        else []
    )
    by_offset = {(d.day - as_of).days: d for d in pool.forecast}
    forecast = [
        ForecastLine(
            horizon=f"J+{k}",
            day=by_offset[k].day,
            free_expected=round(max(0.0, by_offset[k].free_expected), 1),
            free_low=max(0, by_offset[k].free_p10),
            free_high=max(0, by_offset[k].free_p90),
        )
        for k in FORECAST_OFFSETS
        if k in by_offset
    ]
    missing = ["Identifiant ROR de l'unité"]
    if not pool.finess:
        missing.append("FINESS géographique du site")
    return UnitExport(
        site_id=pool.site_id,
        site_name=pool.site_name,
        finess=pool.finess,
        ror_unit_id=None,
        mention=pool.mention,
        unit_label=f"SMR {pool.mention_label}",
        capacities=capacities,
        closures=closures,
        forecast=forecast,
        tension=tension_of(available, pool.beds_installed),
        last_movement_at=pool.last_movement_at,
        missing=missing,
    )
