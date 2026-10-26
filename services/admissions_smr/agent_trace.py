"""Public task diagnostics: fixed labels only, never portal text or model output."""

from __future__ import annotations

import json
import math
from typing import Any, Literal

from pydantic import BaseModel

from services.admissions_smr.agent_policy import ENGINE_NAMES


class RouteStepOut(BaseModel):
    engine: str
    decision: Literal["success", "failure", "skipped", "unverified"]
    reason: str
    cost_usd: float


def safe_reason(raw: object) -> str:
    """Classify untrusted diagnostics without ever returning their text."""
    text = str(raw or "").lower()
    for needle, label in (
        ("budget", "Budget épuisé ou insuffisant"),
        ("désactivé", "Moteur désactivé dans la politique"),
        ("non configuré", "Moteur non configuré sur ce poste"),
        ("identifiant", "Autorisation de voir les données du portail absente"),
        ("calibration", "Calibration du modèle insuffisante ou absente"),
        ("pas de script", "Aucun script disponible pour cette tâche"),
        ("ne répond pas comme prévu", "Le formulaire du portail a changé : script incompatible"),
        ("champ introuvable", "Champ attendu absent du portail"),
        ("relecture", "Relecture impossible ou réponse différente de la décision attendue"),
        ("incertaine", "Réponse incertaine : vérification humaine requise"),
        ("réservation", "Réservation de la tâche perdue ou expirée"),
        ("pause", "Agent mis en pause"),
        ("décision", "Décision remplacée ou non autorisée"),
        ("connexion", "Connexion au portail impossible"),
        ("indisponible", "Moteur indisponible"),
    ):
        if needle in text:
            return label
    return "Le moteur n’a pas pu terminer la tâche ; vérification humaine requise"


def public_route(raw: str | None, status: str) -> list[RouteStepOut]:
    result: Any = json.loads(raw or "{}")
    if not isinstance(result, dict) or not isinstance(result.get("route"), list):
        return []
    steps = []
    for entry in result["route"]:
        if not isinstance(entry, dict) or entry.get("engine") not in ENGINE_NAMES:
            continue
        decision = entry.get("decision")
        cost = entry.get("cost_usd", 0)
        cost = float(cost) if isinstance(cost, int | float) and math.isfinite(cost) else 0.0
        outcome: Literal["success", "failure", "skipped", "unverified"] = "failure"
        if decision == "ignoré":
            outcome = "skipped"
        elif decision == "success":
            outcome = "success" if status == "done" else "unverified"
        reason = (
            "Tâche terminée et contrôlée"
            if outcome == "success"
            else "Résultat du moteur non validé par la relecture indépendante"
            if outcome == "unverified"
            else safe_reason(entry.get("reason") or entry.get("error"))
        )
        steps.append(
            RouteStepOut(
                engine=entry["engine"], decision=outcome, reason=reason, cost_usd=max(0.0, cost)
            )
        )
    return steps
