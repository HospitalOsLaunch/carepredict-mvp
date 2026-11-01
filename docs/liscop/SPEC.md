# Spec : HospitalOS × LISCOP / ARS Hauts-de-France

Statut : **brouillon à valider**. Branche d'intégration `feat/liscop-ars` (part de
`feat/ror-export-maquette`, PR #30), PR finale vers `mvp/computer-use`.

## Objectif

LISCOP (ARS Hauts-de-France, opéré par Inéa) affiche les disponibilités en lits lues dans
le ROR national et prévoit un module de déclaration des tensions. Sa limite est la donnée
d'entrée : déclarations manuelles, fraîcheur de -3 h à -24 h, prévisionnel déclaratif.

HospitalOS doit devenir, pour un établissement, **la source automatique, fraîche et
prédictive** de ces données :

1. sans saisie : les mouvements patients arrivent du SI (HL7 v2 IHE PAM France) ou, à
   défaut, de l'agent de computer use ;
2. au lit près : genre, isolement, lit réellement utilisable ;
3. sur l'aval MCO et les urgences, cœur de cible : lits brancards à 10 h, signal HET ;
4. avec un prévisionnel robuste (arrivées, lits disponibles, tension) à J+1, J+2, J+7,
   calibré et mesuré ;
5. exporté dans le vocabulaire ROR (et pour l'ORU), en lecture seule tant que le
   raccordement n'est pas habilité.

Utilisateurs : bed manager et cellule de gestion des lits, cadres de santé, direction ;
en aval, l'ARS / Inéa / ORU (consommateurs des exports).

Hors périmètre : régulation SAMU/PDSA/SAS/SMUR, gardes médicales, IRM/scanner/labo,
notifications LISCOP, vue territoriale grand public (doublon de LISCOP), envoi réel au ROR.

## Carte des capacités

| Module | Responsabilité | Dépend de |
|---|---|---|
| `bed-registry` | Unités (type, discipline LISCOP), chambres, lits : sexe, isolement, statut (libre, occupé, à nettoyer, bloqué, réservé), affectation séjour ↔ lit | — |
| `movement-ingest` | HL7 v2.5 IHE PAM France (A01, A02, A03, A04, A06, A07, A11, A12, A13, A21, A22, A52, A53, Z99 ; segment ZBE), pseudonymisation, idempotence, annulations ; playbook computer use « relever les mouvements » sur un logiciel de gestion des lits fictif | `bed-registry` |
| `ed-tension` | Recensement des urgences (en attente de lit, hébergés, brancards), indicateur « lits brancards à 10 h » calculé, déclaration manuelle en repli, signal HET / Plan blanc (aide, la décision reste humaine) | `bed-registry`, `movement-ingest` |
| `forecast-engine` | Service séparé de prévision : arrivées par unité, lits disponibles attendus, probabilité de tension, brancards J+1, agrégation groupe/GHT ; intervalles conformes + adaptation en ligne ; backtest à origine glissante contre des références | `bed-registry`, `ed-tension` |
| `ror-oru-export` | Export ROR enrichi (genre, isolement, opérationnel en service / réactivable / supplémentaire, crise-SSE, prévisionnel), correspondance identifiants ROR, file d'envoi en simulation (aucun réseau), export ORU des indicateurs | tous |

Ordre : `bed-registry` (schéma commun des 5 modules) → `movement-ingest` ∥
`forecast-engine` (arrivées) → `ed-tension` → `forecast-engine` (tension) →
`ror-oru-export` → revue, simplification, livraison.

## Choix techniques

| Sujet | Choix | Pourquoi |
|---|---|---|
| Mouvements | HL7 v2.5, extension française IHE PAM (ZBE-1 identifiant de mouvement, ZBE-4 action INSERT/UPDATE/CANCEL) ; parseur `hl7` (python-hl7, BSD) | Standard des GAM en France ; l'ANS publie l'extension nationale |
| Transport | `POST /api/ingest/hl7` (compte de service `ingestion`), accusé ACK/AE/AR ; MLLP en option côté agent | Réutilise l'authentification et l'idempotence existantes |
| Pseudonymisation | IPP/NDA → HMAC-SHA256 avec secret par tenant ; noms, NIR, adresses, dates de naissance jamais stockés (âge en années seulement) | Règle existante du produit : aucune donnée identifiante |
| Prévision | `statsforecast` (Nixtla, Apache-2.0) : SeasonalNaive, AutoETS, AutoTheta, MSTL ; jours fériés `holidays` (MIT) ; vacances scolaires zone B en table | Implémentations standard, rapides, maintenues |
| Intervalles | Conformal split par horizon + ACI (Gibbs & Candès 2021) pour la dérive | Garanties sans hypothèse de loi ; tient en tension |
| Lits disponibles | Simulation Monte Carlo : sorties (modèle existant, Poisson-binomial) − arrivées (échantillons du modèle d'arrivées) − promesses | Donne P(au moins k lits), quantiles, agrégeables |
| Isolation | `services/forecast_engine/` séparé, lancé en tâche planifiée, écrit en base ; l'API lit les résultats | L'API reste légère (pas de numpy/numba dans son image) |

## Commandes

```bash
pip install -r services/admissions_smr/requirements-dev.txt -r services/forecast_engine/requirements.txt
pytest -q
ruff check services tools && ruff format --check services tools
mypy --config-file services/admissions_smr/mypy.ini services/admissions_smr services/admissions_agent services/forecast_engine tools
cd services/admissions_web && npm ci && npm test && npm run build
python -m services.forecast_engine run --group 1          # calcule et stocke les prévisions
python -m services.forecast_engine backtest --group 1     # rapport de backtest
python tools/demo_check.py                                # parcours de démo de bout en bout
```

## Structure

```
services/admissions_smr/domain/{beds,hl7_pam,ed,tension,ror}.py   logique pure, testée
services/admissions_smr/api/routes_{beds,hl7,ed,ror}.py          routes minces
services/admissions_smr/migrations/versions/0003_liscop.py       schéma commun (une migration)
services/forecast_engine/                                         prévision (paquet séparé)
services/admissions_agent/demo_bedsoft/ + playbooks/demo_bedsoft.yaml
services/admissions_web/src/pages/{BedBoard,Urgences,Prevision,Ror}Page.tsx
docs/liscop/{SPEC,PLAN,BACKTEST}.md
```

## Style

Celui du dépôt : domaine pur sans I/O (dataclasses figées), routes minces, schémas
pydantic `Strict`, textes d'interface en français, code et identifiants en anglais,
`ruff` (100 colonnes), `mypy` strict, interface React + Tailwind avec les jetons existants
(couleurs vives, microcopies soignées). Chaque nombre affiché dit d'où il vient.

## Tests

- Domaine : tests unitaires, dont messages HL7 IHE PAM de référence (fixtures).
- API : TestClient sur SQLite, et PostgreSQL via `ADM_TEST_DATABASE_URL`.
- Sécurité : aucun nom/NIR en base après ingestion (test qui inspecte toutes les tables).
- Prévision : backtest à origine glissante sur le générateur synthétique, avec critères
  **fixés avant de regarder les résultats** (ci-dessous) ; rapport `docs/liscop/BACKTEST.md`.
- Web : vitest pour chaque nouvelle page ; démo vérifiée par `tools/demo_check.py`.

## Critères de réussite

1. Rejouer les fixtures IHE PAM produit les bons séjours et lits ; un message rejoué est
   ignoré ; une annulation (A11, A12, A13, ZBE CANCEL) rétablit l'état ; rien
   d'identifiant n'est stocké.
2. Le plan des lits donne, par unité, les lits disponibles par genre et en isolement.
3. « Lits brancards à 10 h » et le signal HET sont calculés à partir du recensement.
4. Prévision, critères pré-enregistrés (horizons J+1 à J+7, ≥ 20 origines) :
   - arrivées : MAE relative à la référence saisonnière < 1 (sinon on garde la
     référence et on le dit) ;
   - intervalles à 80 % : couverture empirique entre 75 et 85 % ;
   - sous une rupture de régime injectée, l'ACI garde la couverture à ±5 points de la
     cible quand l'intervalle statique décroche ;
   - un résultat qui échoue est rapporté tel quel, pas ajusté.
5. L'export ROR contient genre, isolement, opérationnel, prévisionnel ; la colonne J+n
   distingue « libérés non promis » et « disponibles attendus » ; file d'envoi en
   simulation ; export ORU.
6. Tous les contrôles verts ; démo de bout en bout vérifiée.

## Limites

- Toujours : tests avant commit, une PR par livraison, aucune donnée identifiante,
  lecture seule vers l'extérieur.
- À valider d'abord : nouvelles dépendances, changements de schéma hors de ce périmètre,
  CI.
- Jamais : envoi réel au ROR ou à un tiers, secrets en clair, push direct sur
  `mvp/computer-use`, suppression de tests existants.

## Questions ouvertes

1. Dépendances : `statsforecast` (+ numba, pandas, scipy), `holidays`, `hl7`, dans un
   service séparé de l'API. D'accord ?
2. Périmètre : on étend l'application Admissions SMR à l'aval MCO et aux urgences
   (types d'unité), plutôt qu'une application séparée. D'accord ?
3. Données de démo : un CH MCO fictif (urgences, médecine polyvalente, court séjour
   gériatrique, chirurgie, SMR) avec un flux HL7 synthétique. D'accord ?
