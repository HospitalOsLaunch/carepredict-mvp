"""Bed board and availability, at bed level (pure, no I/O).

Definitions (French terms as shown to users):

- **Lit utilisable**: active bed, status ``libre`` (so neither occupied, reserved, blocked
  nor waiting for cleaning), that at least one sex can take given its room (below). A bed
  ``a_nettoyer`` is not available; it is shown as "bientôt" (soon), counted in ``cleaning``.
- **Disponibilité par genre** (ROR "genre de la capacité", TRE_R332 / JDV_J190): the usable
  beds are split into three disjoint groups that add up to the usable beds, as in the ANS
  definitions ("Capacité en lits — indicateurs — définitions" v1.0.1, §2.2 to §2.4):
  ``either`` (indifférencié: a woman or a man can be placed, e.g. a single room or an empty
  double room), ``female`` (a double/multiple room already occupied by a woman, or a bed
  reserved to women), ``male`` (same for men). Which sexes a bed can take: its
  ``sex_constraint`` (``F``, ``M``, ``X`` = both) intersected with the sexes of the patients
  already in the same room. An occupant of unknown sex (``U`` or none) does not restrict the
  room (shortcut: relies on PID-8 of the PAM feed; flag rooms if it proves unreliable).
  A free bed nobody can take (a man and a woman in the room, or a constraint that
  contradicts the occupant) is not usable and is counted in ``sex_conflict``.
  Since 2025-08-28 the ROR code for ``either`` is 04 "Indéterminé" (03 "Indifférencié" is
  deprecated); 01 = Femme, 02 = Homme.
  Two free beds in an empty double room both count as ``either``, as in the ROR definition,
  although placing a woman in one makes the other ``female``.
- **Isolement**: usable beds in an isolation room (``isolation``).
- **Installés**: active beds of the unit. **Fermés**: the larger of the blocked beds and the
  closures declared on the unit (``beds_installed - beds_open`` of ``bed_pools``). Declared
  closures not yet put on a bed reduce the usable beds, taken first from ``either``, then
  ``female``, then ``male`` (the pessimistic choice).
- **Réservés**: beds with status ``reserve`` (a patient is expected within 24 hours, ANS §2.6).
- ``extra_beds`` (lits supplémentaires ouverts) and ``crisis_reserved_beds`` (réservés
  crise / SSE) are the values declared on the unit; they are not part of the usable beds.

Sources: ANS, "ROR — Capacité en lits — Indicateurs — Définitions" v1.0.1
(https://esante.gouv.fr/sites/default/files/media/document/ROR_Capacite-En-Lits_Indicateurs_Definitions_VFD_v1.0.1.pdf);
TRE_R332 GenreCapacite (https://interop.esante.gouv.fr/terminologies/CodeSystem-TRE-R332-GenreCapacite.html).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from services.admissions_smr.domain.tension import Tension, tension_of

BOTH = frozenset({"F", "M"})


@dataclass(frozen=True)
class BedState:
    id: int
    site_id: int
    pool_id: int
    room: str
    label: str
    sex_constraint: str  # F | M | X
    isolation: bool
    status: str  # libre | occupe | a_nettoyer | bloque | reserve
    active: bool = True
    occupant_sex: str | None = None  # F | M | U, when occupied


@dataclass(frozen=True)
class UnitDeclared:
    """What the unit declares in ``bed_pools``."""

    pool_id: int
    beds_installed: int
    beds_open: int
    extra_beds: int = 0
    crisis_reserved_beds: int = 0


@dataclass(frozen=True)
class Availability:
    installed: int
    occupied: int
    reserved: int
    cleaning: int
    blocked: int
    closed: int
    usable: int
    female: int
    male: int
    either: int
    isolation: int
    sex_conflict: int
    extra_beds: int
    crisis_reserved_beds: int

    @property
    def tension(self) -> Tension:
        return tension_of(self.usable, self.installed)


def accepted_sexes(bed: BedState, roommates: Iterable[BedState]) -> frozenset[str]:
    """Sexes a bed can take: its own constraint and the patients already in the room."""
    allowed = BOTH if bed.sex_constraint == "X" else frozenset({bed.sex_constraint}) & BOTH
    present = {b.occupant_sex for b in roommates if b.status == "occupe" and b.active}
    known = frozenset(s for s in present if s in BOTH)
    if known == BOTH:  # a man and a woman already share the room: nobody else fits
        return frozenset()
    return allowed & known if known else allowed


def rooms_of(beds: Iterable[BedState]) -> dict[tuple[int, str], list[BedState]]:
    rooms: dict[tuple[int, str], list[BedState]] = defaultdict(list)
    for b in beds:
        rooms[(b.site_id, b.room)].append(b)
    return rooms


def bed_sexes(beds: Sequence[BedState]) -> dict[int, frozenset[str]]:
    """Accepted sexes of every bed, looking at its room within ``beds``."""
    out: dict[int, frozenset[str]] = {}
    for room in rooms_of(beds).values():
        for b in room:
            out[b.id] = accepted_sexes(b, (r for r in room if r.id != b.id))
    return out


def is_usable(bed: BedState, sexes: frozenset[str]) -> bool:
    return bed.active and bed.status == "libre" and bool(sexes)


def unit_availability(declared: UnitDeclared, beds: Sequence[BedState]) -> Availability:
    """Availability of one unit. ``beds`` must hold every bed of the unit's rooms."""
    sexes = bed_sexes(beds)
    mine = [b for b in beds if b.pool_id == declared.pool_id and b.active]
    count = {s: sum(b.status == s for b in mine) for s in ("occupe", "reserve", "a_nettoyer")}
    blocked = sum(b.status == "bloque" for b in mine)
    free = [b for b in mine if b.status == "libre"]
    usable = [b for b in free if is_usable(b, sexes[b.id])]
    groups = {"either": 0, "female": 0, "male": 0}
    for b in usable:
        s = sexes[b.id]
        groups["either" if s == BOTH else "female" if s == {"F"} else "male"] += 1
    declared_closed = max(0, declared.beds_installed - declared.beds_open)
    shortfall = max(0, declared_closed - blocked)
    for key in ("either", "female", "male"):
        taken = min(shortfall, groups[key])
        groups[key] -= taken
        shortfall -= taken
    total = sum(groups.values())
    return Availability(
        installed=len(mine),
        occupied=count["occupe"],
        reserved=count["reserve"],
        cleaning=count["a_nettoyer"],
        blocked=blocked,
        closed=max(blocked, declared_closed),
        usable=total,
        female=groups["female"],
        male=groups["male"],
        either=groups["either"],
        isolation=min(total, sum(b.isolation for b in usable)),
        sex_conflict=len(free) - len(usable),
        extra_beds=declared.extra_beds,
        crisis_reserved_beds=declared.crisis_reserved_beds,
    )


def add(items: Iterable[Availability]) -> Availability:
    """Sum of several units (a site, a group). The tension is recomputed on the sums."""
    fields = list(Availability.__dataclass_fields__)
    totals = dict.fromkeys(fields, 0)
    for a in items:
        for f in fields:
            totals[f] += getattr(a, f)
    return Availability(**totals)
