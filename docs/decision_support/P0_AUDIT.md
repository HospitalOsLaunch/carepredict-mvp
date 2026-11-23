# P0 — Audit statique de la reprise HospitalOS auto-first

Date : 14 novembre 2026 (Europe/Paris). Méthode : inspection de fichiers, `git ls-remote`,
`git fetch` en lecture de deux refs nommées vers des refs de suivi, `sha256sum`. Aucun merge,
rebase, push, entraînement, chargement de poids, inférence ou installation réseau.

## 1. Paquet de référence

`HospitalOS_Reprise_Codex_Claude_v1` extrait dans un répertoire isolé. `SHA256SUMS.txt` :
8/8 empreintes conformes (plan `bf7e4baf…`, prompt `3bc670e1…`, contrôles `550f2c22…`, 4 sources).
Le plan, le mandat AJ-H, l'état vérifié, la revue patient et la vérification A_detached ont été lus.

## 2. Archives scientifiques — préservées, hors chemin critique

| Archive | SHA-256 attendu | Présente dans cette session | Statut documenté (non réévalué) |
|---|---|---|---|
| `HospitalOS_Lot_A_PRIMARY_20261112.zip` | `a7bf5dcc…9475` | non | PRIMARY terminé à 6 000 (graines 11/23/37), **critères échoués** |
| `HospitalOS_Checkpoint_A_DETACHED_2000_20261112.zip` | `db72732e…387b` | non | A_detached **authentifié à 2 000** pour 11/23/37 ; **final 6 000 non attesté** — ce n'est pas un échec scientifique |

Les commits de bundle `c1a236e8…` et `4b230b19…` n'existent pas dans le clone du dépôt
(`git cat-file` : objet introuvable). Les archives n'étant pas nécessaires à P0–P4, leur absence
ne bloque pas ce mandat ; aucune imitation n'a été recréée. G2 reste `NO-GO`.

## 3. Branches constatées (jamais devinées)

- `main` = `bfa1fa7e…` ; branche de travail initiale de la session = même commit.
- `mvp/computer-use` = `9cddedd6…` : **aucun ancêtre commun avec `main`** (produit admissions
  distinct). Récupérée en lecture pour inspection, non modifiée, non fusionnée.
- `claude/cockpit-web` = `a5e737ee…` : descendant **linéaire** de `main` (merge-base = `bfa1fa7`),
  15 commits : moteur explicite `src/hospitalos/hybrid` (faits `event_time`/`available_at`,
  autorisations de sortie, simulation appariée, workflow d'approbation sandbox) et cockpit
  HospitalOS `web/` (React 18/Vite 6, parcours « libérer → attribuer »).

**Base retenue** pour le moteur et le cockpit : `claude/cockpit-web@a5e737e`. Branche locale
isolée `claude/hospitalos-auto-first-p0-p4-s2dywn` créée depuis cette base (nom imposé par
l'environnement ; équivalent du `feat/ops-planner-auto-v0` proposé). Upstream désactivé.
Une seule base suffit : pas de contrat d'échange entre deux bases.

## 4. Sources historiques à examiner (section 2 du plan)

| Chemin | Constat |
|---|---|
| `src/hospitalos/synthetic/v041/hospsim.py` | présent ; SHA-256 `3c950b50…` ≠ `99f2130c…` de la revue (fichier différent du bundle). Branche « sorties sous pression » toujours présente l. 1084-1093. **Conservé inchangé**, non utilisé par le nouveau moteur. |
| `src/hospitalos/synthetic/policy.py` | présent, empreinte identique à la revue (`6e1a7d99…`). Horloge `fixed UTC+01:00` l. 41 : incompatible avec les changements d'heure ; non réutilisée. |
| `tools/ajh_full_stack/{data,model,generate_data}.py` | **absents** du dépôt (toutes bases inspectées). |
| `tools/corpus_random_paired/pilot_014.py` | **absent**. |

Conséquence : le réseau AJ-H agrégé n'est pas raccordé et n'est pas présenté comme
patient-compatible. Le nouveau backend de référence est un moteur explicite.

## 5. Abstractions réutilisées après vérification

- `hospitalos.operational.contract` : `Closed` (Pydantic fermé/gelé), `Identifier`, `instant` (UTC).
- `hospitalos.hybrid.innovations.uniform` : innovations indexées graine/scénario/mécanisme/entité,
  indépendantes de l'ordre des tirages (base du couplage apparié T22).
- Conventions de `hospitalos.hybrid.models` : `None` = inconnu, autorisation médicale attestée,
  revalidation juste avant décision, réservations distinctes de l'état.
- Cockpit `web/` : jetons `web/src/styles/tokens.css`, vocabulaire « proposée / validée /
  refusée / remplacée », voix et sobriété de `web/DESIGN.md`.

Vérification des bases par tests (via le compteur de budget) :
`tests/hybrid/test_mvp.py` 26 réussis ; `tests/hybrid/test_pathway.py` + `test_future.py` 60 réussis.
`test_decision_guard.py` non exécutable : scikit-learn absent (collecte en erreur, 0,72 s consommées).

## 6. Environnement et manques exacts

- Python 3.13.18 (le dépôt épingle 3.11.9) ; Pydantic 2.13.5 ; NumPy 2.5.3 ; pytest 9.1.1 isolé
  (outil uv) utilisé via `PYTHONPATH`, sans installation. FastAPI, scikit-learn, torch absents.
- Node 22.23.4 ; `tsc` 6.0.2 global ; Playwright global + Chromium préinstallé ; bun 1.4.4.
- **Manque pour le cockpit React** : pas de `web/node_modules` ; le cache npm ne contient aucune
  archive de react, react-dom, vite, vitest, typescript 5.6, jsdom. `npm ci` exigerait une
  installation réseau, non autorisée. Les 66 tests Vitest existants du cockpit ne peuvent donc
  pas être relancés ici.
- Preuves : `artifacts/` et `logs/` sont ignorés par `.gitignore` ; registre et journaux vivent dans `evidence/decision_support/` (`runlogs/`).
- **Décision P4** : brancher la vue décisionnelle dans `web/decision/` comme page sans dépendance,
  compilée par le `tsc` local, réutilisant `tokens.css` du cockpit, servie par un serveur stdlib
  local qui appelle le moteur ; e2e avec le Playwright préinstallé. L'intégration de cette vue
  comme écran React d'`App.tsx` reste à faire après accord distinct pour `npm ci`.
- Le violet de référence `#7049D0` est ajouté comme jeton d'accent limité à cette vue ; le
  cockpit existant utilise `--brand #3047e6` et n'est pas refondu.

## 7. Risques identifiés

1. Fuite du futur via l'évaluateur (initialisation depuis `ready_h` réel) → frontière
   `forecast(public_snapshot, plan, config)` + test de fuite à deux vérités (T03/T04).
2. Réutilisation du mécanisme « sorties sous pression » → absent du nouveau profil, verrou
   `pressure_discharges_enabled=false` vérifié (T07).
3. Incitation perverse « ne pas admettre » → les minutes de soins des patients attribués à
   l'unité mais en attente de lit comptent comme non couvertes ; les admissions ne sont pas un levier.
4. Confusion PRIMARY/A_detached → registre de provenance et rejet (T31).
5. Chiffres codés en dur dans le cockpit → chaque valeur affichée porte un pointeur JSON vers
   un résultat versionné, contrôle statique des littéraux (T32).
6. Budget : 600 s cumulés, 30 s/commande, registre chaîné append-only, arrêt propre (T29).

## 8. Commandes exactes prévues (toutes via `scripts/ds_budget_run.py`)

```bash
export PYTHONPATH=/root/.local/share/uv/tools/pytest/lib/python3.13/site-packages:src:.
python3 scripts/ds_budget_run.py --lot P1 --label schema -- python3 -m pytest -q -p no:cacheprovider tests/decision_support/test_p1_contracts.py
python3 scripts/ds_budget_run.py --lot P2 --label backend -- python3 -m pytest -q -p no:cacheprovider tests/decision_support/test_p2_backend.py
python3 scripts/ds_budget_run.py --lot P3 --label planner -- python3 -m pytest -q -p no:cacheprovider tests/decision_support/test_p3_planner.py
python3 scripts/ds_budget_run.py --lot P3 --label fixtures -- python3 -m hospitalos.decision_support export --out evidence/decision_support/results
python3 scripts/ds_budget_run.py --lot P4 --label tsc -- tsc -p web/decision/tsconfig.json
python3 scripts/ds_budget_run.py --lot P4 --label e2e -- node web/decision/e2e.mjs
python3 scripts/ds_budget_run.py --status
```

Porte P0 : provenance et bases identifiées ; manques nommés. **Franchie.**
