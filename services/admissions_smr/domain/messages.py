"""Reply drafts for the referrer, ready to paste into ViaTrajectoire or an email."""

from __future__ import annotations

from datetime import date

from services.admissions_smr.vocab import MENTIONS, REFUSAL_REASONS

_DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_MONTHS = [
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
]


def french_date(day: date) -> str:
    return f"{_DAYS[day.weekday()]} {day.day} {_MONTHS[day.month - 1]} {day.year}"


def accord_message(
    site_name: str, mention: str, proposed: date, patient_ref: str, referrer_unit: str | None
) -> str:
    to = f"l'équipe {referrer_unit}" if referrer_unit else "l'équipe"
    return (
        f"Bonjour {to},\n\n"
        f"Le {site_name} donne un accord pour l'admission du patient {patient_ref} "
        f"en SMR {MENTIONS.get(mention, mention).lower()}.\n"
        f"Entrée proposée : {french_date(proposed)}.\n\n"
        "Merci de nous confirmer votre choix dès que possible, afin que nous "
        "puissions réserver le lit.\n\n"
        "Bien cordialement,\nLa coordination des admissions"
    )


def refusal_message(
    site_name: str, reason: str, patient_ref: str, comment: str | None, alternative: str | None
) -> str:
    lines = [
        "Bonjour,",
        "",
        f"Le {site_name} ne peut malheureusement pas accueillir le patient {patient_ref}.",
        f"Motif : {REFUSAL_REASONS.get(reason, reason).lower()}.",
    ]
    if comment:
        lines.append(comment)
    if alternative:
        lines += ["", f"Une admission est possible au sein de notre groupe : {alternative}."]
    lines += ["", "Bien cordialement,", "La coordination des admissions"]
    return "\n".join(lines)
