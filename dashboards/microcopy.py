"""French microcopy registry for the Hospitalos dashboard."""

from __future__ import annotations

from typing import Final

APP_TITLE: Final[str] = "Hospitalos — Pilotage prédictif"
APP_SUBTITLE: Final[str] = (
    "Anticipation de la charge soignante par world model RSSM "
    "calibré sur intervalles conformels."
)
APP_FOOTER_TEMPLATE: Final[str] = (
    "Hospitalos · Modèle RSSM v1 · Données synthétiques · {date}"
)

SIDEBAR_BRAND: Final[str] = "Hospitalos"
SIDEBAR_TAGLINE: Final[str] = "Pilotage prédictif"
SIDEBAR_TITLE: Final[str] = "Connexion au modèle"
SIDEBAR_API_LABEL: Final[str] = "Adresse de l'API"
SIDEBAR_API_HELP: Final[str] = (
    "Adresse du service FastAPI exposant le modèle RSSM. "
    "Par défaut : http://localhost:8000."
)
SIDEBAR_TEST_BUTTON: Final[str] = "Tester la connexion"
SIDEBAR_STATUS_OK: Final[str] = "API joignable"
SIDEBAR_STATUS_DOWN: Final[str] = "API injoignable"
SIDEBAR_NAV_TITLE: Final[str] = "Navigation"
SIDEBAR_NAV_FORECAST: Final[str] = "Prévision 48h"
SIDEBAR_NAV_SIMULATION: Final[str] = "Simulation what-if"
SIDEBAR_NAV_EXECUTIVE: Final[str] = "Vue exécutive"
SIDEBAR_NAV_DIAGNOSTICS: Final[str] = "Diagnostics modèle"
SIDEBAR_HELP_TITLE: Final[str] = "Repères de lecture"
SIDEBAR_HELP_OPEN: Final[str] = "Ouvrir le guide rapide"
SIDEBAR_LAST_PREDICTION: Final[str] = "Dernière prédiction : {datetime}"
SIDEBAR_UNDATED: Final[str] = "non datée"
SIDEBAR_STATUS_OK_MARKED: Final[str] = "● API joignable"
SIDEBAR_STATUS_DOWN_MARKED: Final[str] = "● API injoignable"
SIDEBAR_PEAK_TEMPLATE: Final[str] = "Pic prévu : {peak_value} à T+{peak_hours}h"
SIDEBAR_CRITICAL_TEMPLATE: Final[str] = "Créneaux critiques : {count}"
SIDEBAR_FOOTER_TEMPLATE: Final[str] = "Modèle RSSM v1 · {date}"

FCT_TITLE: Final[str] = "Prévision opérationnelle 48 heures"
FCT_SUBTITLE: Final[str] = (
    "Trajectoire probable de la charge soignante sur les 48 prochaines "
    "heures, avec intervalle de confiance à 90 %."
)
FCT_EMPTY_STATE: Final[str] = (
    "Aucune prédiction n'a encore été calculée. Ajustez l'historique "
    "et les actions prévues ci-dessous, puis cliquez sur "
    "« Lancer la prédiction »."
)
FCT_HISTORY_LABEL: Final[str] = "Historique observé"
FCT_HISTORY_COLUMN: Final[str] = "Charge en soins observée"
FCT_HISTORY_HELP: Final[str] = (
    "Charge en soins mesurée sur les 24 dernières heures. "
    "Les valeurs sont éditables pour tester différents contextes."
)
FCT_ACTIONS_LABEL: Final[str] = "Plan d'actions"
FCT_ACTIONS_HELP: Final[str] = (
    "Actions opérationnelles prévues sur l'horizon de prédiction "
    "(admissions, sorties, chirurgies, transferts, redéploiements). "
    "Modifiez ces valeurs pour explorer différents scénarios."
)
FCT_HORIZON_LABEL: Final[str] = "Horizon de prédiction (heures)"
FCT_HORIZON_HELP: Final[str] = (
    "Nombre d'heures à prédire dans le futur. Maximum 48h. "
    "Au-delà, l'incertitude devient trop élevée pour être actionnable."
)
FCT_RUN_BUTTON: Final[str] = "Lancer la prédiction"
FCT_LOADING: Final[str] = "Calcul de la prédiction en cours (5 à 10 secondes)…"
FCT_SUCCESS: Final[str] = "Prédiction calculée. Consultez le graphique ci-dessous."
FCT_KPI_GLOBAL_LOAD: Final[str] = "Charge globale"
FCT_KPI_GLOBAL_LOAD_SUB: Final[str] = "Référence seuil 850"
FCT_KPI_PEAK: Final[str] = "Pic prévu"
FCT_KPI_PEAK_SUB_TEMPLATE: Final[str] = "à T+{hours}h"
FCT_KPI_CRITICAL: Final[str] = "Créneaux critiques"
FCT_KPI_CRITICAL_SUB: Final[str] = "sur 48h"
FCT_KPI_INTERVAL: Final[str] = "Intervalle moyen"
FCT_KPI_INTERVAL_SUB: Final[str] = "Largeur IC 90 %"
FCT_KPI_CONFIDENCE: Final[str] = "Confiance modèle"
FCT_KPI_CONFIDENCE_SUB: Final[str] = "Calibration conformelle"
FCT_DETAILS_EXPANDER: Final[str] = "Détails par créneau"
FCT_SYNTHESIS_TEMPLATE: Final[str] = (
    "Pic SIIPS prévu à T+{peak_hours}h : {peak_value} "
    "(IC 90 % [{lower}–{upper}]). "
    "{critical_count} créneau{plural} horaire{plural} en situation "
    "critique sur 48h. "
    "Marge moyenne au seuil critique : {margin}."
)
FCT_CHART_SUBTITLE: Final[str] = "SIIPS : charge soignante horaire par patient"

SIM_TITLE: Final[str] = "Simulation what-if"
SIM_SUBTITLE: Final[str] = (
    "Comparez deux plans d'actions opérationnelles pour anticiper "
    "leur impact respectif sur la charge soignante."
)
SIM_EMPTY_STATE: Final[str] = (
    "Définissez deux plans d'actions (Plan A et Plan B) ci-dessous, "
    "puis cliquez sur « Comparer les plans » pour visualiser leur "
    "impact sur les 48 prochaines heures."
)
SIM_PLAN_A_TITLE: Final[str] = "Plan A — Situation actuelle"
SIM_PLAN_A_HELP: Final[str] = (
    "Plan d'actions actuellement prévu, sans modification. "
    "Sert de référence pour la comparaison."
)
SIM_PLAN_B_TITLE: Final[str] = "Plan B — Action envisagée"
SIM_PLAN_B_HELP: Final[str] = (
    "Plan d'actions modifié à tester. Ajustez les valeurs pour "
    "explorer l'impact d'une intervention opérationnelle."
)
SIM_RUN_BUTTON: Final[str] = "Comparer les plans"
SIM_LOADING: Final[str] = "Comparaison des deux plans en cours (10 à 20 secondes)…"
SIM_SUMMARY_TEMPLATE: Final[str] = (
    "Le Plan B {direction} la charge totale de {delta_pct} sur 48h. "
    "{critical_change}"
)
SIM_DIRECTION_REDUCES: Final[str] = "réduit"
SIM_DIRECTION_INCREASES: Final[str] = "augmente"
SIM_DIRECTION_STABLE: Final[str] = "maintient"
SIM_CRITICAL_FEWER_TEMPLATE: Final[str] = (
    "Il génère {n} créneau{plural} critique{plural} de moins que le Plan A."
)
SIM_CRITICAL_MORE_TEMPLATE: Final[str] = (
    "Il génère {n} créneau{plural} critique{plural} de plus que le Plan A."
)
SIM_CRITICAL_SAME: Final[str] = "Les deux plans génèrent autant de créneaux critiques."
SIM_DETAILS_EXPANDER: Final[str] = "Détails de la comparaison"

EXE_TITLE: Final[str] = "Vue exécutive"
EXE_SUBTITLE: Final[str] = "Synthèse opérationnelle dérivée de la dernière prédiction."
EXE_EMPTY_STATE: Final[str] = (
    "Aucune prédiction disponible. Rendez-vous dans l'onglet "
    "« Prévision 48h » et lancez d'abord une prédiction."
)
EXE_STATUS_LABEL: Final[str] = "Statut système"
EXE_STATUS_HELP: Final[str] = (
    "Niveau d'alerte global, calculé à partir du nombre de créneaux "
    "critiques sur 48h."
)
EXE_STATUS_STABLE: Final[str] = "Stable"
EXE_STATUS_WATCH: Final[str] = "Sous surveillance"
EXE_STATUS_CRITICAL: Final[str] = "Critique"
EXE_PEAK_LABEL: Final[str] = "Pic prévu (48h)"
EXE_MODEL_LABEL: Final[str] = "Modèle"
EXE_MODEL_HELP: Final[str] = (
    "Identifiant de la version de modèle ayant produit la dernière prédiction."
)
EXE_SERVICES_TITLE: Final[str] = "Service supervisé"
EXE_CURRENT_SIIPS_TEMPLATE: Final[str] = "SIIPS actuel : {value}"
EXE_PEAK_SIIPS_SUB: Final[str] = "SIIPS prévu maximal sur 48h"
EXE_ALERTS_TITLE: Final[str] = "Alertes prédictives"
EXE_NO_ALERTS: Final[str] = "Aucune alerte critique sur les 48 prochaines heures."
EXE_ALERT_TEMPLATE: Final[str] = (
    "Dépassement du seuil critique prévu à T+{hours}h. "
    "SIIPS prédit : {value} (IC 90 % [{lower}–{upper}])."
)
EXE_PROPAGATION_NOTE: Final[str] = (
    "Le modèle prédit la charge service par service. "
    "La propagation inter-services nécessite une instance dédiée "
    "par service et n'est pas exposée dans cette démonstration."
)
EXE_ALERT_KICKER_TEMPLATE: Final[str] = "T+{hours}h"
EXE_ACTION_SIMULATE: Final[str] = "Simuler une intervention"
EXE_ACTION_DETAIL: Final[str] = "Voir le détail"
EXE_ACTION_NOTIFY: Final[str] = "Notifier le cadre"
EXE_ACTION_NOTIFY_HELP: Final[str] = "Fonctionnalité prévue dans une version ultérieure."
EXE_ACTION_SIMULATE_INFO: Final[str] = (
    "Rendez-vous dans l'onglet « Simulation what-if » pour tester une intervention."
)
EXE_ACTION_DETAIL_INFO: Final[str] = (
    "Consultez l'onglet « Prévision 48h » pour le graphique complet "
    "et les détails par créneau."
)

DIAG_TITLE: Final[str] = "Diagnostics modèle"
DIAG_SUBTITLE: Final[str] = (
    "Transparence du modèle : architecture, calibration, limites "
    "et instructions de reproduction."
)
DIAG_TRAINING_TITLE: Final[str] = "Courbes d'entraînement"
DIAG_TRAINING_MISSING: Final[str] = (
    "Le fichier artifacts/training_curves.png est absent. "
    "Régénérez-le avec :\n"
    "    python scripts/train_rssm_synthetic.py --plot"
)
DIAG_MODEL_CARD_TITLE: Final[str] = "Fiche modèle"
DIAG_LIMITS_TITLE: Final[str] = "Limites connues"
DIAG_REPRO_TITLE: Final[str] = "Reproductibilité"
DIAG_REPRO_SUBTITLE: Final[str] = (
    "Commandes exactes pour reproduire l'environnement de démonstration."
)
DIAG_CONFORMAL_TITLE: Final[str] = "Couverture conformelle"
DIAG_CONFORMAL_MISSING: Final[str] = "Résidus conformels non disponibles."
DIAG_CONFORMAL_EMPTY: Final[str] = "Le fichier de résidus conformels est vide ou illisible."
DIAG_RESIDUAL_X_AXIS: Final[str] = "Erreur absolue (points SIIPS)"
DIAG_RESIDUAL_Y_AXIS: Final[str] = "Fréquence"
DIAG_LIMIT_SYNTHETIC: Final[str] = "Modèle entraîné uniquement sur données synthétiques"
DIAG_LIMIT_SCOPE: Final[str] = "Périmètre actuel : un service, un établissement"
DIAG_LIMIT_FEDERATED: Final[str] = "Federated learning conçu mais non validé empiriquement"
DIAG_LIMIT_CLINICAL: Final[str] = (
    "Sans validation clinique : non utilisable comme dispositif médical"
)
DIAG_ARCHITECTURE_LABEL: Final[str] = "Architecture"
DIAG_CALIBRATION_LABEL: Final[str] = "Calibration"
DIAG_TRAINING_TEMPLATE: Final[str] = (
    "Entraînement actuel : {steps} steps sur SIIPS synthétique calibré"
)
DIAG_REFERENCE: Final[str] = (
    "Référence : Hafner et al. 2023, « Mastering Diverse Domains through World Models » "
    "(DreamerV3)"
)
DIAG_TRAIN_COMMAND: Final[str] = "python scripts/train_rssm_synthetic.py --plot"
DIAG_SERVE_COMMAND: Final[str] = "uvicorn services.api.main:app --port 8000"
DIAG_DEMO_COMMAND: Final[str] = "bash docs/demo/run_demo.sh"

ERR_API_UNREACHABLE_TITLE: Final[str] = "Le modèle n'est pas joignable"
ERR_API_UNREACHABLE_BODY: Final[str] = (
    "Le service de prédiction ne répond pas à l'adresse indiquée. "
    "Vérifiez que l'API FastAPI est démarrée sur le port 8000 :\n"
    "    uvicorn services.api.main:app --port 8000"
)
ERR_API_VALIDATION_TITLE: Final[str] = "Les données saisies sont invalides"
ERR_API_VALIDATION_BODY: Final[str] = (
    "Le modèle a rejeté la requête. Vérifiez le format de l'historique "
    "et du plan d'actions ci-dessous."
)
ERR_API_SERVER_TITLE: Final[str] = "Le modèle a rencontré un problème"
ERR_API_SERVER_BODY: Final[str] = (
    "Une erreur interne au modèle est survenue. Consultez les logs "
    "du serveur FastAPI pour le détail technique."
)
ERR_UNEXPECTED_TITLE: Final[str] = "Action impossible"
ERR_UNEXPECTED_BODY: Final[str] = (
    "Une erreur inattendue s'est produite. Rechargez la page "
    "(touche F5) et réessayez."
)
TECHNICAL_DETAILS: Final[str] = "Détails techniques"

HELP_INTRO: Final[str] = (
    "Hospitalos anticipe la charge soignante des services hospitaliers "
    "à l'aide d'un modèle de prédiction calibré (RSSM)."
)
HELP_HOW_IT_WORKS_TITLE: Final[str] = "Comment lire les prédictions"
HELP_HOW_IT_WORKS_BODY: Final[str] = (
    "Le modèle observe l'historique récent et les actions planifiées, "
    "puis calcule la trajectoire la plus probable de la charge en "
    "soins (SIIPS) pour les 48 prochaines heures. L'intervalle de "
    "confiance à 90 % indique la plage dans laquelle la valeur réelle "
    "tombera dans 9 cas sur 10."
)
HELP_GLOSSARY_TITLE: Final[str] = "Glossaire"
HELP_GLOSSARY_INTRO: Final[str] = "Définitions des termes utilisés dans le tableau de bord."
HELP_USE_CASES_TITLE: Final[str] = "Cas d'usage"
HELP_USE_CASES_BODY: Final[str] = (
    "**Anticiper une saturation** : consultez l'onglet "
    "« Prévision 48h » pour identifier les créneaux à risque.\n\n"
    "**Évaluer une décision** : utilisez « Simulation what-if » "
    "pour comparer l'impact de deux plans d'actions.\n\n"
    "**Préparer une revue** : la « Vue exécutive » synthétise "
    "l'état du service en une seule page."
)
HELP_CLOSE: Final[str] = "Fermer le guide"

CHART_HISTORY: Final[str] = "Historique"
CHART_FORECAST_MEDIAN: Final[str] = "Prévision médiane"
CHART_INTERVAL: Final[str] = "Intervalle 90 %"
CHART_CRITICAL_THRESHOLD: Final[str] = "Seuil critique"
CHART_PEAK: Final[str] = "Pic prévu"
CHART_X_AXIS: Final[str] = "Horizon opérationnel (heures)"
CHART_Y_AXIS: Final[str] = "Charge en soins prévue (SIIPS)"
CHART_LEGEND: Final[str] = "Lecture"
CHART_PLAN_LEGEND: Final[str] = "Plans évalués"
CHART_COMPARISON_TITLE: Final[str] = "Comparaison Plan A / Plan B sur 48h"

TABLE_HOUR: Final[str] = "Horaire (h)"
TABLE_FORECAST: Final[str] = "Charge en soins prévue"
TABLE_LOW: Final[str] = "Borne basse"
TABLE_HIGH: Final[str] = "Borne haute"
TABLE_CRITICAL: Final[str] = "Situation critique"
TABLE_PLAN_A: Final[str] = "Plan A (SIIPS)"
TABLE_PLAN_A_IC: Final[str] = "Plan A IC"
TABLE_PLAN_B: Final[str] = "Plan B (SIIPS)"
TABLE_PLAN_B_IC: Final[str] = "Plan B IC"
TABLE_DIFFERENCE: Final[str] = "Différence"
TABLE_CRITICAL_SHORT: Final[str] = "Critique ?"
