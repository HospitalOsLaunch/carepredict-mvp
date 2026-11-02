"""What HospitalOS could send to the national ROR for each unit (pure, no I/O).

Nothing here talks to the ROR. The module turns what HospitalOS knows (bed-level
availability, declared closures, extra and crisis beds, the stored forecasts) into the
capacity vocabulary of the ROR, so that the export can be shown to and discussed with the
regional teams that read it (LISCOP in Hauts-de-France, through Inéa).

Vocabularies (ANS terminologies, https://interop.esante.gouv.fr/terminologies/):

- JDV_J187_NatureCapacite_ROR: 01 Lit (02 Place, 04 Salle unused here).
- JDV_J188_TypeStatutCapacite_ROR: 01 Installé, 02 Disponible, 03 Occupé, 04 Réservé,
  05 Fermé, 06 Supplémentaire.
- JDV_J189_TemporaliteCapacite_ROR: 01 Courant, 03 Prévisionnel 24 heures, 04 Prévisionnel
  48 heures, 05 Prévisionnel 7 jours (02 Prévisionnel 1 heure unused).
- JDV_J190_GenreCapacite_ROR: 01 Femme, 02 Homme, 04 Indéterminé (03 Indifférencié is
  deprecated since 2025-08-28).
- JDV_J191_TypeFermetureCapacite_ROR: 01 Réactivable, 02 Non réactivable, 03 Indéterminé.

The ROR FHIR IG carries one capacity per combination of these codes, in the
``ror-location-supported-capacity`` extension (sub-extensions ``capacityType``,
``capacityStatus``, ``temporalityCapacity``, ``nbCapacity``, ``genderCapacityAvailable``,
``capacityClosingType``, ``capacityUpdateDate``...). ``ror_records`` produces that shape.
``capacitySourceType`` (J193), ``additionalBedType`` (J192), ``crisisType`` (J194) and
``temporaryAssignement`` (J195) are left empty: their codes could not be checked here.

Proposals still to validate with the ANS and the regional teams: the mapping of internal
closure reasons to J191, and the forecast block (J+1, J+2, J+7 as J189 temporalities).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime

from services.admissions_smr.domain.beds import Availability

# The LISCOP tension legend lives in domain.tension; re-exported for existing callers.
from services.admissions_smr.domain.tension import TENSION_NORMAL_MIN as TENSION_NORMAL_MIN
from services.admissions_smr.domain.tension import Tension as Tension
from services.admissions_smr.domain.tension import tension_of as tension_of

Code = tuple[str, str]

# --- ANS vocabularies -------------------------------------------------------------------

NATURE_BED: Code = ("01", "Lit")

STATUS_INSTALLED: Code = ("01", "Installé")
STATUS_AVAILABLE: Code = ("02", "Disponible")
STATUS_OCCUPIED: Code = ("03", "Occupé")
STATUS_RESERVED: Code = ("04", "Réservé")
STATUS_CLOSED: Code = ("05", "Fermé")
STATUS_EXTRA: Code = ("06", "Supplémentaire")

TEMPORALITY_CURRENT: Code = ("01", "Courant")
# Forecast horizons shown by LISCOP next to the capacity, as J189 temporalities.
TEMPORALITY_BY_OFFSET: dict[int, Code] = {
    1: ("03", "Prévisionnel 24 heures"),
    2: ("04", "Prévisionnel 48 heures"),
    7: ("05", "Prévisionnel 7 jours"),
}
FORECAST_OFFSETS: tuple[int, ...] = tuple(TEMPORALITY_BY_OFFSET)

GENDER_FEMALE: Code = ("01", "Femme")
GENDER_MALE: Code = ("02", "Homme")
GENDER_UNDETERMINED: Code = ("04", "Indéterminé")

CLOSURE_REACTIVABLE: Code = ("01", "Réactivable")
CLOSURE_NOT_REACTIVABLE: Code = ("02", "Non réactivable")
CLOSURE_UNDETERMINED: Code = ("03", "Indéterminé")

# Proposed mapping of the closure reasons (vocab.CAPACITY_REASONS) to J191. Staffing and
# seasonal closures can be reopened when needed; works cannot. To validate.
CLOSURE_TYPE_BY_REASON: dict[str, Code] = {
    "personnel": CLOSURE_REACTIVABLE,
    "saisonnier": CLOSURE_REACTIVABLE,
    "travaux": CLOSURE_NOT_REACTIVABLE,
}
# A blocked bed (breakdown, cleaning problem...) has a free-text reason: type unknown.
BLOCKED_REASON = "lit_bloque"

# --- forecast modes: never mixed, always labelled ---------------------------------------

MODE_EXPECTED = "disponibles_attendus"
MODE_RELEASED = "liberes_non_promis"
MODE_NONE = "aucune"
FORECAST_MODES: dict[str, str] = {
    MODE_EXPECTED: "Disponibles attendus : lits ouverts − présents − admissions promises "
    "+ sorties prévues − arrivées non programmées prévues (moteur de prévision).",
    MODE_RELEASED: "Libérés non promis : lits libres d'après la seule prévision des sorties, "
    "sans les arrivées non programmées (aucune prévision stockée pour l'unité).",
    MODE_NONE: "Pas de prévision pour cette unité.",
}

# Freshness: which signal gave the latest change of the unit.
FRESHNESS_SOURCES: dict[str, str] = {
    "mouvement": "mouvement patient reçu (HL7 ou agent)",
    "lit": "changement de statut d'un lit",
    "capacite": "changement de capacité déclaré",
    "saisie": "séjour saisi ou modifié",
}


@dataclass(frozen=True)
class ForecastPoint:
    day: date
    mean: float
    low: float  # q10
    high: float  # q90
    p_tension: float | None = None
    p_critique: float | None = None


@dataclass(frozen=True)
class ForecastSource:
    mode: str  # MODE_*
    points: Sequence[ForecastPoint] = ()
    model: str | None = None
    as_of: date | None = None
    computed_at: datetime | None = None


NO_FORECAST = ForecastSource(MODE_NONE)


@dataclass(frozen=True)
class UnitSnapshot:
    site_id: int
    site_name: str
    finess: str | None
    pool_id: int
    code: str
    label: str
    unit_type: str
    discipline: str
    ror_unit_id: str | None
    beds_installed: int  # declared on the unit
    beds_open: int
    extra_beds: int
    crisis_reserved_beds: int
    closure_reason: str  # reason of the latest capacity change
    availability: Availability | None  # bed level; None when the unit has no bed rows
    occupied: int = 0  # pool level only: patients present
    reserved_24h: int = 0  # pool level only: admissions promised for today or tomorrow
    forecast: ForecastSource = NO_FORECAST
    changes: Mapping[str, datetime | None] = field(default_factory=dict)  # FRESHNESS_SOURCES


@dataclass(frozen=True)
class CapacityLine:
    code: str
    label: str
    count: int
    note: str | None = None


@dataclass(frozen=True)
class ClosureLine:
    code: str
    label: str
    count: int
    internal_reason: str


@dataclass(frozen=True)
class GenderSplit:
    """Available beds by J190 gender. ``None``: not known (unit without bed rows)."""

    female: int | None
    male: int | None
    undetermined: int | None
    total: int
    isolation: int | None
    level: str  # lit | unite


@dataclass(frozen=True)
class Operational:
    """LISCOP "capacité opérationnelle"."""

    in_service: int  # installed − closed
    reactivable: int  # closed beds of J191 type 01
    extra: int  # extra beds opened (J188 06)


@dataclass(frozen=True)
class ForecastLine:
    horizon: str
    day: date
    temporality: Code
    mean: float
    low: int
    high: int
    p_tension: float | None
    p_critique: float | None


@dataclass(frozen=True)
class ForecastBlock:
    mode: str
    label: str
    model: str | None
    as_of: date | None
    computed_at: datetime | None
    lines: list[ForecastLine]


@dataclass(frozen=True)
class Freshness:
    at: datetime
    source: str


@dataclass(frozen=True)
class RorRecord:
    """One capacity in the shape of the ROR FHIR ``supported-capacity`` extension."""

    status: Code
    temporality: Code
    count: int
    gender: Code | None = None
    closing_type: Code | None = None
    update_date: datetime | None = None
    nature: Code = NATURE_BED


@dataclass(frozen=True)
class UnitExport:
    site_id: int
    site_name: str
    finess: str | None
    pool_id: int
    code: str
    label: str
    unit_type: str
    discipline: str
    ror_unit_id: str | None
    capacities: list[CapacityLine]
    closures: list[ClosureLine]
    gender: GenderSplit
    operational: Operational
    crisis_reserved: int
    forecast: ForecastBlock
    tension: Tension
    freshness: Freshness | None
    records: list[RorRecord]
    missing: list[str]


def closure_type(reason: str) -> Code:
    return CLOSURE_TYPE_BY_REASON.get(reason, CLOSURE_UNDETERMINED)


def available_beds(beds_open: int, occupied: int, reserved_24h: int) -> int:
    """J188 "disponible" at unit level: a patient can be placed now and the bed is not
    promised within 24 hours. Open beds are taken as staffed."""
    return max(0, beds_open - occupied - reserved_24h)


def closures(declared_closed: int, reason: str, blocked: int) -> list[ClosureLine]:
    """Declared closures typed by their reason; blocked beds beyond them: undetermined."""
    out = []
    if declared_closed > 0:
        out.append(ClosureLine(*closure_type(reason), declared_closed, reason))
    if blocked > declared_closed:
        out.append(ClosureLine(*CLOSURE_UNDETERMINED, blocked - declared_closed, BLOCKED_REASON))
    return out


def freshness(changes: Mapping[str, datetime | None]) -> Freshness | None:
    """The latest change of the unit and the signal it came from."""
    known = [(at, source) for source, at in changes.items() if at is not None]
    if not known:
        return None
    at, source = max(known)
    return Freshness(at, source)


def forecast_block(source: ForecastSource, today: date) -> ForecastBlock:
    """J+1, J+2, J+7 counted from ``today``; a horizon the source does not cover is left out."""
    by_offset = {(p.day - today).days: p for p in source.points}
    lines = [
        ForecastLine(
            horizon=f"J+{k}",
            day=p.day,
            temporality=TEMPORALITY_BY_OFFSET[k],
            mean=round(max(0.0, p.mean), 1),
            low=max(0, round(p.low)),
            high=max(0, round(p.high)),
            p_tension=p.p_tension,
            p_critique=p.p_critique,
        )
        for k in FORECAST_OFFSETS
        if (p := by_offset.get(k)) is not None
    ]
    mode = source.mode if lines else MODE_NONE
    return ForecastBlock(
        mode=mode,
        label=FORECAST_MODES[mode],
        model=source.model if lines else None,
        as_of=source.as_of if lines else None,
        computed_at=source.computed_at if lines else None,
        lines=lines,
    )


def ror_records(
    capacities: Sequence[CapacityLine],
    closed: Sequence[ClosureLine],
    gender: GenderSplit,
    forecast: ForecastBlock,
    fresh: Freshness | None,
) -> list[RorRecord]:
    """One record per (status, temporality, gender, closure type), as the ROR stores them.

    Only "disponibles attendus" become forecast records: "libérés non promis" ignore the
    unscheduled arrivals and are not a ROR availability.
    """
    at = fresh.at if fresh else None
    count = {c.code: c.count for c in capacities}
    out = [RorRecord(STATUS_INSTALLED, TEMPORALITY_CURRENT, count["01"], update_date=at)]
    if gender.level == "lit":
        for code, n in (
            (GENDER_FEMALE, gender.female),
            (GENDER_MALE, gender.male),
            (GENDER_UNDETERMINED, gender.undetermined),
        ):
            out.append(RorRecord(STATUS_AVAILABLE, TEMPORALITY_CURRENT, n or 0, code, None, at))
    else:
        out.append(RorRecord(STATUS_AVAILABLE, TEMPORALITY_CURRENT, gender.total, update_date=at))
    out.append(RorRecord(STATUS_OCCUPIED, TEMPORALITY_CURRENT, count["03"], update_date=at))
    out.append(RorRecord(STATUS_RESERVED, TEMPORALITY_CURRENT, count["04"], update_date=at))
    for c in closed:
        out.append(
            RorRecord(STATUS_CLOSED, TEMPORALITY_CURRENT, c.count, None, (c.code, c.label), at)
        )
    if count["06"]:
        out.append(RorRecord(STATUS_EXTRA, TEMPORALITY_CURRENT, count["06"], update_date=at))
    if forecast.mode == MODE_EXPECTED:
        for line in forecast.lines:
            # nbCapacity is an integer: the rounded mean of the scenarios.
            out.append(
                RorRecord(
                    STATUS_AVAILABLE,
                    line.temporality,
                    max(0, round(line.mean)),
                    update_date=forecast.computed_at,
                )
            )
    return out


def unit_export(u: UnitSnapshot, today: date) -> UnitExport:
    a = u.availability
    if a is not None:
        installed, occupied, reserved, closed = a.installed, a.occupied, a.reserved, a.closed
        available, blocked = a.usable, a.blocked
        gender = GenderSplit(a.female, a.male, a.either, a.usable, a.isolation, "lit")
        note = (
            f"Lits utilisables ; {a.cleaning} à nettoyer, comptés ni disponibles ni occupés."
            if a.cleaning
            else "Lits utilisables (libres, au bon genre, ni bloqués ni réservés)."
        )
        reserved_note = "Lits réservés à un patient attendu dans les 24 h."
    else:
        installed, occupied, reserved = u.beds_installed, u.occupied, u.reserved_24h
        closed, blocked = max(0, u.beds_installed - u.beds_open), 0
        available = available_beds(u.beds_open, occupied, reserved)
        gender = GenderSplit(None, None, None, available, None, "unite")
        note = "Calcul à l'unité (pas de plan des lits) : ouverts − présents − promis 24 h."
        reserved_note = "Admissions déjà accordées pour aujourd'hui ou demain."
    closed_lines = closures(max(0, u.beds_installed - u.beds_open), u.closure_reason, blocked)
    capacities = [
        CapacityLine(*STATUS_INSTALLED, installed),
        CapacityLine(*STATUS_AVAILABLE, available, note),
        CapacityLine(*STATUS_OCCUPIED, occupied),
        CapacityLine(*STATUS_RESERVED, reserved, reserved_note),
        CapacityLine(*STATUS_CLOSED, closed),
        CapacityLine(*STATUS_EXTRA, u.extra_beds, "Lits supplémentaires ouverts, déclarés."),
    ]
    operational = Operational(
        in_service=max(0, installed - closed),
        reactivable=sum(c.count for c in closed_lines if c.code == CLOSURE_REACTIVABLE[0]),
        extra=u.extra_beds,
    )
    block = forecast_block(u.forecast, today)
    fresh = freshness(u.changes)
    missing = []
    if not u.ror_unit_id:
        missing.append("Identifiant ROR de l'unité")
    if not u.finess:
        missing.append("FINESS géographique du site")
    if a is None:
        missing.append("Plan des lits (disponibilité par genre et isolement)")
    return UnitExport(
        site_id=u.site_id,
        site_name=u.site_name,
        finess=u.finess,
        pool_id=u.pool_id,
        code=u.code,
        label=u.label,
        unit_type=u.unit_type,
        discipline=u.discipline,
        ror_unit_id=u.ror_unit_id,
        capacities=capacities,
        closures=closed_lines,
        gender=gender,
        operational=operational,
        crisis_reserved=u.crisis_reserved_beds,
        forecast=block,
        tension=tension_of(available, installed),
        freshness=fresh,
        records=ror_records(capacities, closed_lines, gender, block, fresh),
        missing=missing,
    )
