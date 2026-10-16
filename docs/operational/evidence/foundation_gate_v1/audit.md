# E0 — Audit de faisabilité du benchmark de fondation

Date : 16 octobre 2026. Type : **audit documentaire et des entrées accessibles**.
Ce rapport n'est pas une expérience prédictive et ne contient aucun score de modèle.

## Résultat

**E1 synthétique : BLOQUÉ — observations originales complètes non récupérées.**
**E2 réel opérationnel : BLOQUÉ — aucun jeu admissible identifié dans les sources inspectées.**
**Valeur du pré-entraînement synthétique : NON ÉVALUÉE.**

Ce résultat concerne la possibilité de lancer le benchmark, pas la qualité d'un
modèle. Aucun modèle de fondation n'a été exécuté, aucun réseau n'a été réentraîné,
aucun test final réservé n'a été ouvert.

## Vérifications effectuées

| Entrée | Observation vérifiée | Conséquence |
|---|---|---|
| Dépôt `main` | Commit `bfa1fa7e0a8bbdd8817157a162d65f507568a251`, arbre `2f96c97ae2bdfc13697d46127fcca1987fc090e6` ; lots 1–16 intégrés | Base de reprise identifiée |
| CI après fusion | `ci`, `operational-foundation` et `synthetic-foundation` réussis sur ce commit | Validation technique ; aucune validation de transfert réel |
| Dépendances | `uni2ts` et MLflow déclarés ; `uni2ts` pointe vers `main` | Dépendance présente dans le projet, mais révision d'inférence à figer |
| Preuves lot 16 | Poids, configurations, registres, rapports et empreintes présents ; `predictions_frozen.json` contient des empreintes de fichiers NPZ | Les empreintes ne sont pas les matrices d'observation ni les prédictions elles-mêmes |
| Artefacts GitHub des runs du lot 16 et de `main` | Aucun artefact du workflow opérationnel ; manifeste annuel et rapports du workflow synthétique | La liste des chemins archivés ne contient pas les observations complètes des cohortes du benchmark lot 16 |
| Espace de calcul de cette session | Aucun paquet de cohortes ; PyTorch, Uni2TS, Chronos et TimesFM absents | Environnement et entrées à préparer ; installer les bibliothèques seul ne débloque pas les données |
| Fichier utilisateur `mimic_sample.csv` | En-tête et aperçu lus : admissions, démographie, diagnostics, signes vitaux et notes ; pas d'identifiant d'unité/site, sortie/transfert, série d'occupation ou date de disponibilité | Non admissible à la cible opérationnelle ; provenance réelle non attestée par son nom |
| MIMIC-IV officiel | Décalage des dates indépendant par patient ; périmètre ED/ICU | Additionner des séjours décalés ne donne pas le recensement temporel réel de l'hôpital |
| eICU officiel | Soins critiques multisites ; temps relatifs aux séjours | Pas un test de flux simultanés de tout l'hôpital ou GHT |

L'inspection du CSV porte sur son schéma et un aperçu, pas sur un audit complet
des lignes. Aucun contenu patient ni extrait de note n'est publié dans ce rapport.
L'absence d'un fichier dans les sources inspectées ne prouve pas sa disparition
sur l'ancien ordinateur ou dans un autre espace de stockage.

## Éléments nécessaires pour débloquer

### E1 : comparaison sur les mondes déjà utilisés

Récupérer le paquet d'observations, topologies et vérités des deux cohortes du
lot 16, avec les manifestes correspondants. Pour réutiliser les méthodes du lot 17,
ajouter ses poids, prédictions, protocole, code exact et manifestes originaux.
Vérifier les empreintes avant utilisation ; ne pas substituer une reconstruction
à un résultat historique. Les poids du réseau du lot 16 peuvent être rechargés,
sans refaire son entraînement.

### E2 : première comparaison sur une vraie série opérationnelle

Un export agrégé suffit pour commencer : identifiant pseudonyme du site et du
périmètre, occupation à pas horaire ou quotidien explicitement choisi, capacité
ouverte, horodatage commun et date réelle de disponibilité, topologie datée,
couverture de population et provenance. Les autres cibles sont ajoutées seulement
quand leur mesure existe. Pour le benchmark horaire t+24 h du lot 16, ne pas
interpoler artificiellement des données quotidiennes en 24 observations.

Conserver ensemble les établissements qui partagent des ressources. Documenter
les changements de périmètre/codage. Un export rétrospectif sans historique de
disponibilité reste une expérience rétrospective, pas une preuve de fonctionnement
en connexion réelle. Les données individuelles protégées ne sont pas à déposer
dans ce dépôt public.

## Références vérifiables

- [Base intégrée](https://github.com/HospitalOsLaunch/carepredict-mvp/commit/bfa1fa7e0a8bbdd8817157a162d65f507568a251).
- [CI générale](https://github.com/HospitalOsLaunch/carepredict-mvp/actions/runs/38865305362), [opérationnelle](https://github.com/HospitalOsLaunch/carepredict-mvp/actions/runs/38865304152), [synthétique](https://github.com/HospitalOsLaunch/carepredict-mvp/actions/runs/38865304195).
- [Chemins archivés par CI](https://github.com/HospitalOsLaunch/carepredict-mvp/blob/bfa1fa7e0a8bbdd8817157a162d65f507568a251/.github/workflows/synthetic-foundation.yml).
- [Preuves lot 16](https://github.com/HospitalOsLaunch/carepredict-mvp/tree/bfa1fa7e0a8bbdd8817157a162d65f507568a251/docs/operational/evidence/lot16).
- [MIMIC-IV](https://physionet.org/content/mimiciv/3.1/), [eICU temps](https://eicu.mit.edu/about/eicu/), [eICU patient](https://eicu.mit.edu/eicutables/patient/).

Le [plan d'expériences](../../protocols/foundation_gate_v1.md) décrit les portes
suivantes. Le registre de lancement doit être complété avant toute nouvelle mesure.
