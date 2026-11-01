"""Tension: level of a unit (LISCOP legend) and the HET / Plan blanc decision aid.

Unit level, LISCOP legend for health-care units ("sanitaire"): usable beds over installed
beds; ``normal`` from 20 %, ``critique`` at 0 usable bed, ``tension`` in between. Taken from
the LISCOP service presentation; to confirm with the ARS.

HET decision aid. The "Hôpital en tension" and "Plan blanc" declarations are acts of the
hospital management (direction): the product never declares anything. It only applies a
transparent rule set to the census and returns which criteria are met, with their values
and thresholds, so the person who decides sees why a declaration is suggested:

- ``boarding_10h``: patients on a stretcher at 10:00 (see ``domain.ed``) ≥ threshold;
- ``waiting_bed``: patients waiting for a bed in the emergency department now ≥ threshold;
- ``longest_wait_hours``: longest wait for a bed since the admission decision ≥ threshold;
- ``critical_units_share``: share of MCO units at ``critique`` ≥ threshold.

Level: no criterion met → ``aucun``; one → ``vigilance``; two or more → ``het_suggere``.
Default thresholds (``HetThresholds``) are starting points for a ~250-bed general hospital
with about 120 emergency visits a day; they must be calibrated with the direction and the
ARS before use (shortcut: stored in code until a group settings column exists).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

# --- unit level (LISCOP legend) -----------------------------------------------------------

TENSION_NORMAL_MIN = 0.20


@dataclass(frozen=True)
class Tension:
    level: str  # normal | tension | critique
    availability_rate: float | None


def tension_of(available: int, installed: int) -> Tension:
    if installed <= 0:
        return Tension(level="normal", availability_rate=None)
    rate = available / installed
    if available <= 0:
        level = "critique"
    elif rate < TENSION_NORMAL_MIN:
        level = "tension"
    else:
        level = "normal"
    return Tension(level=level, availability_rate=round(rate, 4))


# --- declarations (a human act) -------------------------------------------------------------

DECLARATION_LEVELS: dict[str, dict[str, str]] = {
    "het": {"niveau_1": "Niveau 1", "niveau_2": "Niveau 2"},
    "plan_blanc": {"alerte": "Mise en alerte", "declenche": "Déclenché"},
}

# --- HET decision aid -----------------------------------------------------------------------

AID_LEVELS: dict[str, str] = {
    "aucun": "Aucun signal",
    "vigilance": "Vigilance",
    "het_suggere": "Déclaration HET à envisager",
}


@dataclass(frozen=True)
class HetThresholds:
    boarding_10h: int = 5
    waiting_bed: int = 10
    longest_wait_hours: float = 12.0
    critical_units_share: float = 0.25


@dataclass(frozen=True)
class HetInputs:
    boarding_10h: int
    waiting_bed: int
    longest_wait_hours: float | None
    critical_units: int
    mco_units: int


@dataclass(frozen=True)
class Criterion:
    code: str
    label: str
    value: float | None
    threshold: float
    triggered: bool


@dataclass(frozen=True)
class HetAid:
    level: str
    criteria: Sequence[Criterion]

    @property
    def triggered(self) -> list[Criterion]:
        return [c for c in self.criteria if c.triggered]


def het_aid(inputs: HetInputs, thresholds: HetThresholds | None = None) -> HetAid:
    t = thresholds or HetThresholds()
    share = inputs.critical_units / inputs.mco_units if inputs.mco_units else None

    def crit(code: str, label: str, value: float | None, threshold: float) -> Criterion:
        return Criterion(code, label, value, threshold, value is not None and value >= threshold)

    criteria = [
        crit("boarding_10h", "Lits brancards à 10 h", inputs.boarding_10h, t.boarding_10h),
        crit("waiting_bed", "Patients en attente de lit", inputs.waiting_bed, t.waiting_bed),
        crit(
            "longest_wait_hours",
            "Attente de lit la plus longue (heures)",
            None if inputs.longest_wait_hours is None else round(inputs.longest_wait_hours, 1),
            t.longest_wait_hours,
        ),
        crit(
            "critical_units_share",
            "Part des unités MCO en niveau critique",
            None if share is None else round(share, 4),
            t.critical_units_share,
        ),
    ]
    met = sum(c.triggered for c in criteria)
    level = "aucun" if met == 0 else "vigilance" if met == 1 else "het_suggere"
    return HetAid(level=level, criteria=criteria)
