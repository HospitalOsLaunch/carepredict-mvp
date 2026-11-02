"""Calendar features: French public holidays and school holidays of zone B (Hauts-de-France).

Public holidays come from the ``holidays`` package (MIT), country "FR" (metropolitan
France). School holidays are a small dated table: académies of Amiens and Lille, both
in zone B. Source: ministère de l'Éducation nationale, calendrier scolaire officiel,
https://www.education.gouv.fr/calendrier-scolaire-100148 (arrêtés fixant le calendrier
des années scolaires 2025-2026 et 2026-2027). Dates are the official ones: the table
stores [fin des cours, reprise des cours), classes ending after school on the first date
(a Saturday, or a Wednesday before the Ascension bridge).
The 2026-2027 lines must be checked against the published arrêté before any real use
(the page could not be fetched when this table was written).

The demo generator has no holiday effect, so the models do not take these features as
regressors (they would fit noise); they are used for diagnostics: the mean forecast error
on holidays versus other days, reported with each run.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

import holidays

# [fin des cours, reprise des cours), zone B.
SCHOOL_HOLIDAYS_ZONE_B: tuple[tuple[date, date, str], ...] = (
    (date(2025, 7, 5), date(2025, 9, 1), "Vacances d'été 2025"),
    (date(2025, 10, 18), date(2025, 11, 3), "Toussaint 2025"),
    (date(2025, 12, 20), date(2026, 1, 5), "Noël 2025"),
    (date(2026, 2, 14), date(2026, 3, 2), "Hiver 2026 (zone B)"),
    (date(2026, 4, 11), date(2026, 4, 27), "Printemps 2026 (zone B)"),
    (date(2026, 5, 13), date(2026, 5, 18), "Pont de l'Ascension 2026"),
    (date(2026, 7, 4), date(2026, 9, 1), "Vacances d'été 2026"),
    (date(2026, 10, 17), date(2026, 11, 2), "Toussaint 2026"),
    (date(2026, 12, 19), date(2027, 1, 4), "Noël 2026"),
    (date(2027, 2, 20), date(2027, 3, 8), "Hiver 2027 (zone B, à vérifier)"),
    (date(2027, 4, 17), date(2027, 5, 3), "Printemps 2027 (zone B, à vérifier)"),
    (date(2027, 7, 3), date(2027, 9, 1), "Vacances d'été 2027 (à vérifier)"),
)
SCHOOL_TABLE_RANGE = (date(2025, 7, 5), date(2027, 8, 31))


def public_holidays(years: Iterable[int]) -> dict[date, str]:
    """French public holidays (metropolitan France) for the given years."""
    return dict(holidays.country_holidays("FR", years=sorted(set(years)), language="fr").items())


def is_school_holiday(day: date) -> bool | None:
    """True / False inside the table's range, None outside (unknown, not "no holiday")."""
    if not SCHOOL_TABLE_RANGE[0] <= day <= SCHOOL_TABLE_RANGE[1]:
        return None
    return any(start <= day < end for start, end, _ in SCHOOL_HOLIDAYS_ZONE_B)


def day_kinds(start: date, end: date) -> dict[date, str]:
    """Each day of [start, end] labelled ``ferie``, ``vacances``, ``ordinaire`` or ``inconnu``."""
    off = public_holidays(range(start.year, end.year + 1))
    out: dict[date, str] = {}
    day = start
    while day <= end:
        school = is_school_holiday(day)
        if day in off:
            out[day] = "ferie"
        elif school is None:
            out[day] = "inconnu"
        else:
            out[day] = "vacances" if school else "ordinaire"
        day += timedelta(days=1)
    return out
