"""Controlled vocabularies shared by the API, the imports and the UI.

Codes are stable ASCII identifiers; labels are the French wording shown to users.
"""

from __future__ import annotations

from typing import Final

# SMR "mentions" (specialised rehabilitation activities, 2022 SMR reform).
MENTIONS: Final[dict[str, str]] = {
    "polyvalent": "Polyvalent",
    "geriatrie": "Gériatrie",
    "locomoteur": "Locomoteur",
    "neuro": "Système nerveux",
    "cardio": "Cardio-vasculaire",
    "pneumo": "Pneumologie",
    "digestif_nutrition": "Digestif, endocrinologie, nutrition",
    "oncologie": "Oncologie et hématologie",
    "addictologie": "Conduites addictives",
    "pediatrie": "Pédiatrie",
    "brules": "Brûlés",
}

REQUEST_SOURCES: Final[dict[str, str]] = {
    "viatrajectoire": "ViaTrajectoire",
    "mail": "Mail",
    "fax": "Fax",
    "telephone": "Téléphone",
    "autre": "Autre",
}

# Request lifecycle. "accord" = SMR answered yes with a proposed date;
# "confirmee" = the referrer chose this SMR; "perdue" = referrer went elsewhere
# or cancelled after the request was received.
REQUEST_STATUSES: Final[dict[str, str]] = {
    "nouvelle": "Nouvelle",
    "en_etude": "En étude",
    "accord": "Accord envoyé",
    "confirmee": "Confirmée",
    "admise": "Admise",
    "refusee": "Refusée",
    "perdue": "Perdue",
}

OPEN_STATUSES: Final[frozenset[str]] = frozenset({"nouvelle", "en_etude", "accord", "confirmee"})
AWAITING_RESPONSE_STATUSES: Final[frozenset[str]] = frozenset({"nouvelle", "en_etude"})
RESPONDED_STATUSES: Final[frozenset[str]] = frozenset({"accord", "refusee"})

ALLOWED_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "nouvelle": frozenset({"en_etude", "accord", "refusee", "perdue"}),
    "en_etude": frozenset({"accord", "refusee", "perdue", "nouvelle"}),
    "accord": frozenset({"confirmee", "admise", "perdue", "refusee", "en_etude"}),
    "confirmee": frozenset({"admise", "perdue", "accord", "en_etude"}),
    "admise": frozenset(),
    "refusee": frozenset({"en_etude"}),
    "perdue": frozenset({"en_etude"}),
}

REFUSAL_REASONS: Final[dict[str, str]] = {
    "pas_de_lit": "Pas de lit disponible à la date souhaitée",
    "mention_inadaptee": "Mention ou spécialité inadaptée",
    "charge_en_soins": "Charge en soins trop lourde pour l'équipe",
    "besoin_technique": "Besoin technique non couvert (O2, dialyse…)",
    "isolement": "Isolement impossible",
    "projet_inadapte": "Projet de rééducation inadapté",
    "dossier_incomplet": "Dossier incomplet",
    "autre": "Autre motif",
}

LOSS_REASONS: Final[dict[str, str]] = {
    "autre_etablissement": "L'adresseur a choisi un autre établissement",
    "retour_domicile": "Retour à domicile",
    "etat_clinique": "Évolution de l'état clinique",
    "annulation_adresseur": "Annulation par l'adresseur",
    "deces": "Décès",
    "autre": "Autre motif",
}

CAPACITY_REASONS: Final[dict[str, str]] = {
    "personnel": "Manque de personnel",
    "travaux": "Travaux ou maintenance",
    "saisonnier": "Fermeture saisonnière",
    "ouverture": "Ouverture ou réouverture de lits",
    "autre": "Autre",
}

SPECIAL_NEEDS: Final[dict[str, str]] = {
    "oxygene": "Oxygénothérapie",
    "nutrition_enterale": "Nutrition entérale",
    "dialyse": "Dialyse",
    "tracheotomie": "Trachéotomie",
    "ventilation": "Ventilation non invasive",
    "bariatrique": "Matériel bariatrique",
    "chimiotherapie": "Chimiothérapie",
}

ROLES: Final[dict[str, str]] = {
    "admin_groupe": "Administrateur du groupe",
    "coordination": "Coordination des admissions",
    "direction": "Direction (lecture)",
    "ingestion": "Compte de service (ingestion)",
}

WRITE_ROLES: Final[frozenset[str]] = frozenset({"admin_groupe", "coordination"})
READ_ROLES: Final[frozenset[str]] = frozenset({"admin_groupe", "coordination", "direction"})
