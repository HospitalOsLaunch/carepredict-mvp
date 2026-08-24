"""Glossary definitions and tooltip helpers for the Hospitalos dashboard."""

from __future__ import annotations

from html import escape
from typing import Final

GLOSSARY: Final[dict[str, str]] = {
    "SIIPS": (
        "Soins Infirmiers Individualisés à la Personne Soignée. "
        "Indicateur normalisé mesurant la charge soignante horaire "
        "par patient. Référentiel national reconnu en France."
    ),
    "Seuil critique": (
        "Valeur de SIIPS au-delà de laquelle le service est considéré "
        "comme saturé. Calibré sur le 95e percentile de la distribution "
        "historique du service. Valeur de référence : 850."
    ),
    "Intervalle de confiance 90 %": (
        "Plage de valeurs dans laquelle la prédiction tombera 9 fois "
        "sur 10. Calculée par calibration conformelle sur des données "
        "indépendantes de l'entraînement."
    ),
    "Conformal prediction": (
        "Méthode statistique de quantification de l'incertitude "
        "garantissant une couverture exacte (90 %) sans hypothèse "
        "sur la distribution sous-jacente."
    ),
    "RSSM": (
        "Recurrent State-Space Model. Architecture neuronale "
        "DreamerV3-style combinant un état déterministe (GRU) et "
        "un état stochastique gaussien pour modéliser la dynamique "
        "temporelle du système hospitalier."
    ),
    "Pic prévu": (
        "Valeur maximale de SIIPS anticipée sur l'horizon de prédiction. "
        "Marquée par un losange orange sur le graphique."
    ),
    "Créneau critique": (
        "Heure pour laquelle la prédiction médiane dépasse le seuil critique du service."
    ),
    "Horizon de prédiction": (
        "Nombre d'heures dans le futur pour lesquelles le modèle "
        "calcule une prédiction. Limité à 48h pour préserver la fiabilité."
    ),
    "Plan d'actions": (
        "Liste d'actions opérationnelles planifiées sur l'horizon "
        "(admissions, sorties, chirurgies, transferts, redéploiements). "
        "Le modèle évalue leur impact sur la charge."
    ),
    "Vue exécutive": (
        "Synthèse opérationnelle destinée à un Directeur des Soins "
        "ou un Directeur d'établissement. Présente l'état actuel "
        "du service et les alertes prédictives à 48h."
    ),
}


def get_definition(term: str) -> str | None:
    """Return the definition for a term, or None if not in glossary."""
    return GLOSSARY.get(term)


def term_tooltip(term: str) -> str:
    """Return the glossary definition for a term, or the term itself."""
    return GLOSSARY.get(term, term)


def render_term(term: str) -> str:
    """Return markdown rendering the term with an info marker and tooltip."""
    definition = term_tooltip(term)
    return f'{escape(term)} <span title="{escape(definition)}">ⓘ</span>'
