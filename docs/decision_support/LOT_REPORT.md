# Rapport par lot — reprise HospitalOS auto-first P0–P4

Statut de livraison : **`PARTIAL_WITH_CHECKPOINT`** depuis l'audit indépendant du 14 novembre
2026 (constats F01–F08, corrigés en P2/P3bis ; portes restantes : Python 3.11.9 non testable hors
ligne, ré-audit indépendant). Voir `CORRECTIONS_REPORT.md` et `STATUS.json` du paquet.
L'annonce initiale `P0_P4_TECHNICAL_PASS` est conservée ci-dessous à titre historique : elle était
prématurée, les tests livrés ne couvrant pas les contre-exemples A01–A09.
Statut scientifique : `PROTOTYPE_UNVALIDATED` · `clinical_validation=false` · `G2=NO-GO`.
Toutes les exécutions sont dans `evidence/decision_support/BUDGET_LEDGER.jsonl` (registre chaîné,
journaux et SHA-256 dans `runlogs/`). Aucun push, merge, rebase, entraînement, chargement de
poids, inférence AJ-H, appel payant, installation réseau ou processus laissé actif.

## P0 — Audit statique (porte franchie)

`docs/decision_support/P0_AUDIT.md`, `evidence/decision_support/BASE_MAP.json`.
Base : `claude/cockpit-web@a5e737e`, descendant linéaire de `main@bfa1fa7`. `mvp/computer-use`
(historique sans ancêtre commun) non touchée. Archives PRIMARY/A_detached absentes de la session,
non nécessaires, statuts documentés conservés. `hospsim.py` diffère du bundle relu ; `tools/ajh_*`
absents. Vérification de base : 86 tests hybrides préexistants passés ; `test_decision_guard.py`
non exécutable (scikit-learn absent). Budget consommé en P0 : 3,06 s.

## P1 — Contrats (porte franchie)

Contrats Pydantic fermés (`contracts.py`), schémas JSON (`contracts/decision_support/`),
`UNIT_PROFILE.json`, `OBJECTIVE_CONFIG.json` (OBJ-LEX-1), `PRESSURE_SCORE_CONFIG.json`
(PS-EXP-1, `EXPERIMENTAL_SYNTHETIC`), `DATA_DICTIONARY.md`, fixtures synthétiques générées par
`tests/decision_support/fixtures/build_fixtures.py` (nominal auto, vérité privée B, sans action,
données insuffisantes, X1/X2, hypothèse, impossible, contradictoire). 10 tests P1 passés.

## P2 — Backend de référence sûr (porte franchie)

`reference_forecaster.py` : frontière `forecast(PublicSnapshot, Plan, config)`, innovations
indexées appariées, vérité privée séparée, oracle privé refusé comme backend produit, profil sans
« sorties sous pression », vérificateur d'invariants indépendant. `resources.py` : compétences,
présence simultanée, engagements extérieurs, registre idempotent. 14 tests P2 passés.

**Défaut réel trouvé et corrigé** : T14 a d'abord échoué — refuser l'admission de A02 faisait
baisser les minutes non couvertes (910 < 930), car la tâche d'admission disparaissait. Règle
ajoutée : le travail d'admission d'un patient arrivé non admis reste dû en fin d'horizon.
`OBJECTIVE_CONFIG.json` a été complété en conséquence (modification tracée, avant toute
exploitation des résultats de planification).

## P3 — Planificateur et recommandation (porte franchie)

`candidates.py`, `planner.py` (`recommend` / `simulate` / `review`), `export.py`, commande
`python -m hospitalos.decision_support`. Résultats réellement produits dans
`evidence/decision_support/results/` (11 fichiers indexés par SHA-256 dans `index.json`).

Sur la fixture nominale, **sans scénario saisi** : 12 plans admissibles énumérés, 12 évalués
(recherche complète sur cet univers borné). Rejets motivés : S03/S04/S07 non autorisés,
S05 autorisation révoquée, S06 obstacle aval, S02 sans créneau avant son départ prévu,
R3 viole le minimum de l'unité prêteuse. Plan prioritaire : coordination de la sortie de S01
(départ visé 10:00) + renforts R1 et R2. Minutes non couvertes (moyenne sur 4 scénarios de
sélection) : pratique habituelle 1040 → plan 435 ; attente de lit 21,5 → 14,5 patients·h ;
renfort 10 h. Résultat **conditionnel** à R1 (demandé, non confirmé) : sans R1, 795 minutes.
Alternative distincte : R1 + R2 sans coordination (640). Ces chiffres sont des sorties d'une
fixture synthétique, pas des objectifs codés ni des preuves d'efficacité.

Évaluation sur graines disjointes 901–904 (`evaluation_out_of_sample_nominal.json`) : mêmes
valeurs (1040 / 435) — la fixture est quasi déterministe ; c'est un contrôle de séparation des
graines, pas une mesure de performance. Rejeu oracle privé (évaluation seule) : 1025 / 420.

15 tests P3 + 5 tests d'audit passés. Corrections de tests (indices horaires 10 h Paris = 14,
12 h = 16 ; T29 : la commande est coupée au reliquat de budget) consignées dans le registre.

## P4 — Cockpit auto puis manuel (porte franchie)

`web/decision/` : page sans dépendance, compilée par le `tsc` local, réutilisant `tokens.css`
et `app.css` du cockpit `web/` ; serveur stdlib local (`serve.py`, 127.0.0.1, aucun point
d'exécution) qui appelle le moteur. Ouverture = proposition automatique ; « Modifier » ouvre le
mode X1/X2 prérempli ; « Valider (démo) » n'envoie rien. Chaque chiffre porte `data-src`
(document + pointeur JSON) et `data-raw`.

e2e Playwright (`web/decision/e2e.mjs`) : 19/19 contrôles (auto sans saisie, traçabilité de tous
les chiffres, verrous affichés dans les compléments, hypothèse non approuvable, invalidation puis
recalcul après révocation, abstention, sans action, pas de défilement horizontal à 390 px).
Deux défauts d'interface trouvés et corrigés : attribut `hidden` écrasé par `display:grid`,
débordement de 54 px sur mobile. Captures : `evidence/decision_support/captures/`.

Limite initiale (levée en P4b) : l'intégration React demandait `npm ci`, non autorisé à ce stade.

## P4b — Intégration au cockpit React (après accord distinct pour `npm ci` dans `web/`)

`npm ci` : 182 paquets en 3,43 s (installation tracée et imputée au registre). Base du cockpit
vérifiée **avant** modification : typecheck propre, 66/66 tests Vitest.

Nouvelle route **« Plan 24 h »** (`#/plan`, raccourci `P`) dans `web/src/App.tsx` :
`web/src/ui/DecisionPlan.tsx`, `web/src/data/useDecision.ts`, `web/src/api/decision.ts`,
`web/src/styles/decision.css` (classes `panel`, `btn`, `pill`, `table`, `page-head` du cockpit ;
violet `#7049D0` limité à l'écran). À l'arrivée sur la route, la recommandation automatique est
calculée sans saisie ; « Modifier » ouvre le formulaire X1/X2 prérempli.

- API locale : Vite relaie `/api/decision/*` vers `web/decision/serve.py` (127.0.0.1:8765).
- Sans API : sorties du vrai moteur embarquées (`web/src/fixtures/decision.json`, générées par
  `web/dev/build_decision_fixtures.py` ; trajectoires des plans non affichés retirées, SHA-256 de la
  sortie complète conservé). La saisie libre X1/X2 exige l'API ; hors-ligne, trois scénarios
  précalculés par le moteur sont proposés.
- L'écran Unité existant est inchangé ; sur la route Plan, le bandeau de démonstration et
  l'horloge de l'unité hybride sont masqués pour ne pas mélanger deux unités fictives.

Contrôles : typecheck propre ; **71/71 tests Vitest** (66 existants + 5 nouveaux : auto sans saisie,
traçabilité de chaque chiffre, validation de démo sans commande, scénarios manuels dont hypothèse
non approuvable et impossible, abstention, envoi des verrous X1/X2 au moteur) ; build de production ;
**e2e Playwright 17/17** sur le cockpit construit contre le moteur réel (`web/decision/e2e_react.mjs`).
Défauts trouvés et corrigés : plantage sur un scénario manuel `INFEASIBLE` (bundle sans plan
prioritaire), pastille étirée, mots coupés dans le tableau, en-têtes rognés. Avertissement Vite
conservé : bundle JavaScript > 500 ko (données de démonstration embarquées).
Captures : `evidence/decision_support/captures/react_*.png`.

Non-régression : 86 tests hybrides préexistants repassés après les modifications ; `ruff` propre
sur les nouveaux fichiers ; `mypy --strict` non exécuté.

## Matrice T01–T32 (identifiants stables)

| ID | Test(s) | Statut |
|---|---|---|
| T01 | `test_audit::test_t01_*` ; `restore.sh` (arrêt si SHA-256 faux) | passé |
| T02 | `test_p1::test_t02_*` | passé |
| T03 | `test_p2::test_t03_*` | passé |
| T04 | `test_p2::test_t04_*` | passé |
| T05 | `test_p2::test_t05_*`, `test_p3::test_t10_t27_*`, e2e | passé |
| T06 | `test_p3::test_t06_*`, e2e | passé |
| T07 | `test_p2::test_t07_*` | passé |
| T08 | `test_p2::test_t08_*` | passé |
| T09 | `test_p2::test_t09_t21_*`, `test_p3::test_t09_*` | passé |
| T10 | `test_p2::test_t10_*`, `test_p3::test_t10_t27_*` | passé |
| T11 | `test_p2::test_t11_*`, e2e | passé |
| T12 | `test_p2::test_t12_*` | passé |
| T13 | `test_p2::test_t13_*` | passé |
| T14 | `test_p2::test_t14_*` (échec initial → correction) | passé |
| T15 | `test_p3::test_t15_*`, e2e | passé |
| T16 | `test_p3::test_t16_*`, e2e | passé |
| T17 | `test_p3::test_t17_*`, e2e | passé |
| T18 | `test_p3::test_t18_*`, e2e | passé |
| T19 | `test_p3::test_t19_*`, `sweep_x2_extension_t.json` | passé |
| T20 | `test_p3::test_t20_*` | passé |
| T21 | `test_p2::test_t09_t21_*` | passé |
| T22 | `test_p2::test_t22_*` | passé |
| T23 | `test_p3::test_t23_*` | passé |
| T24 | `test_p3::test_t24_*` | passé |
| T25 | `test_p3::test_t25_*` | passé |
| T26 | `test_p1::test_t26_*`, `test_p3::test_t26_*` | passé |
| T27 | `test_p3::test_t10_t27_*`, e2e | passé |
| T28 | `test_p1::test_t28_*` (25 h / 23 h, ambiguïté, inexistence) | passé |
| T29 | `test_audit::test_t29_*` + compteur réel | passé |
| T30 | `restore.sh` dans un dossier neuf (reçu `RESTORE_RECEIPT.json`) | voir reçu |
| T31 | `test_audit::test_t31_*` | passé |
| T32 | `test_audit::test_t32_*` (statique) + e2e (dynamique) | passé |
