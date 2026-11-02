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
    "portail": "Autre portail d'orientation",
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

# --- LISCOP / ROR: MCO units, beds, emergency department, tension --------------------------

# Kind of unit (bed_pools.unit_type). SMR units keep "smr".
UNIT_TYPES: Final[dict[str, str]] = {
    "smr": "Soins médicaux et de réadaptation",
    "medecine": "Médecine",
    "chirurgie": "Chirurgie",
    "soins_critiques": "Soins critiques",
    "urgences": "Urgences",
    "perinatalite": "Périnatalité",
    "sante_mentale": "Santé mentale",
    "medico_social": "Médico-social",
}

# The seven disciplines LISCOP displays (bed_pools.discipline).
LISCOP_DISCIPLINES: Final[dict[str, str]] = {
    "soins_critiques": "Soins critiques",
    "perinatalite": "Périnatalité",
    "chirurgie": "Chirurgie",
    "medecine": "Médecine",
    "sante_mentale": "Santé mentale",
    "smr": "SMR",
    "medico_social": "Médico-social (grand âge)",
}

# MCO unit codes (bed_pools.mention for an MCO unit).
MCO_UNITS: Final[dict[str, str]] = {
    "urgences": "Urgences",
    "medecine_polyvalente": "Médecine polyvalente",
    "court_sejour_geriatrique": "Court séjour gériatrique",
    "cardiologie": "Cardiologie",
    "chirurgie_viscerale": "Chirurgie viscérale",
    "chirurgie_orthopedique": "Chirurgie orthopédique",
    "reanimation": "Réanimation",
}

# MCO unit code -> (unit_type, discipline). An SMR mention is ("smr", "smr").
UNIT_KINDS: Final[dict[str, tuple[str, str]]] = {
    "urgences": ("urgences", "medecine"),
    "medecine_polyvalente": ("medecine", "medecine"),
    "court_sejour_geriatrique": ("medecine", "medecine"),
    "cardiologie": ("medecine", "medecine"),
    "chirurgie_viscerale": ("chirurgie", "chirurgie"),
    "chirurgie_orthopedique": ("chirurgie", "chirurgie"),
    "reanimation": ("soins_critiques", "soins_critiques"),
}

# Every code a unit (bed_pools.mention, stays.mention) may carry.
UNIT_CODES: Final[dict[str, str]] = MENTIONS | MCO_UNITS

BED_STATUSES: Final[dict[str, str]] = {
    "libre": "Libre",
    "occupe": "Occupé",
    "a_nettoyer": "À nettoyer",
    "bloque": "Bloqué",
    "reserve": "Réservé",
}

# Why a bed is blocked: a code, never free text, so no patient name ends up on the board
# or in the audit log. A short optional note (BED_NOTE_MAX characters) is shown on the
# board but kept out of the audit detail.
BED_BLOCK_REASONS: Final[dict[str, str]] = {
    "travaux": "Travaux",
    "equipement": "Équipement en panne",
    "hygiene_isolement": "Hygiène, isolement",
    "personnel": "Manque de personnel",
    "autre": "Autre",
}
BED_NOTE_MAX: Final = 80

SEX_CONSTRAINTS: Final[dict[str, str]] = {
    "X": "Indifférencié",
    "F": "Femmes",
    "M": "Hommes",
}

STAY_SOURCES: Final[dict[str, str]] = {
    "saisie": "Saisie",
    "hl7": "Mouvement HL7",
    "agent": "Agent",
    "import": "Import",
}

ADMISSION_MODES: Final[dict[str, str]] = {
    "urgences": "Par les urgences",
    "programme": "Programmée",
    "mutation": "Mutation interne",
    "transfert": "Transfert d'un autre établissement",
}

ED_OUTCOMES: Final[dict[str, str]] = {
    "hospitalise": "Hospitalisé",
    "sortie": "Retour à domicile",
    "transfert": "Transféré",
    "fugue": "Parti sans attendre",
    "deces": "Décédé",
}

TENSION_KINDS: Final[dict[str, str]] = {
    "het": "Hôpital en tension",
    "plan_blanc": "Plan blanc",
}

# --- LISCOP forecasts: written by services/forecast_engine, read by the API ------------------

FORECAST_SCOPES: Final[tuple[str, ...]] = ("unit", "site", "group", "ght", "departement")
FORECAST_TARGETS: Final[tuple[str, ...]] = (
    "arrivals",
    "discharges",
    "available_beds",
    "tension_prob",
    "boarding_10h",
    "ed_arrivals",  # beyond the LISCOP contract: emergency department arrivals per site
)
# A run is stale when it is not today's or older than this (the job runs at least daily).
FORECAST_STALE_AFTER_HOURS: Final = 26
# Groups generated by the demo seeders (seed.py, seed_mco.py): our own simulator's numbers.
SYNTHETIC_GROUPS: Final[frozenset[str]] = frozenset(
    {"Centre hospitalier des Deux-Rivières (fictif)", "Groupe Démo Réadaptation"}
)
