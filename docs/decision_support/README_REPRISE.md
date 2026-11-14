# Démarrage local — aide à la décision HospitalOS (auto-first, P0–P4)

Prototype local sur données **synthétiques**. Aucune action réelle, aucun SIH, aucun réseau requis.

## Prérequis constatés

- Python ≥ 3.11 (exécuté ici en 3.13.18) avec `pydantic` 2.x et `numpy` ; `jsonschema` pour un test.
- `pytest` ≥ 8 (ici 9.1.1 depuis un environnement isolé ajouté par `PYTHONPATH`).
- Pour la vue : `tsc` (TypeScript ≥ 5) ; pour l'e2e : Node ≥ 18 et Playwright avec Chromium.
- Aucune dépendance npm du cockpit React n'est nécessaire pour cette vue.

## Commandes

```bash
export PYTHONPATH=src:.            # + chemin de pytest si installé hors de l'interpréteur
python3 -m pytest -q tests/decision_support          # 44 tests (T01..T32 hors T30)
python3 -m hospitalos.decision_support recommend tests/decision_support/fixtures/nominal_auto.json
python3 -m hospitalos.decision_support simulate tests/decision_support/fixtures/scenario_x1x2.json
python3 -m hospitalos.decision_support export --out evidence/decision_support/results
tsc -p web/decision/tsconfig.json                     # régénère web/decision/js/decision.js
python3 web/decision/serve.py --port 8765             # puis http://127.0.0.1:8765/ ; Ctrl-C pour arrêter
node web/decision/e2e.mjs                             # e2e (démarre et arrête lui-même le serveur)
```

Pour rester dans le cadre budgété de la reprise, préfixer chaque commande d'exécution par
`python3 scripts/ds_budget_run.py --lot <lot> --label "<texte>" --` (600 s cumulées,
30 s par commande, registre chaîné jamais remis à zéro ; `--status` affiche le reste).

## Ce que montre la vue

1. À l'ouverture : la proposition calculée automatiquement (ou l'abstention, ou « rien à
   changer »), ses actions, effets, besoins IDE, conditions, incertitudes et la trajectoire.
2. « Valider (démo) », « Refuser », « Modifier ». Valider n'envoie aucune commande.
3. « Simuler un scénario » / « Modifier » : verrous X1 (sortie à une heure), X2 (présence
   prolongée de t heures depuis une heure de référence visible), renforts imposés/exclus,
   échéance « demain HH:MM ». Même moteur, branches comparables.
4. Démo « nouvelle information » : révocation de l'autorisation de S01 ⇒ validation invalidée,
   recalcul explicite.

## Fichiers

- Moteur : `src/hospitalos/decision_support/` ; configs : `configs/decision_support/` ;
  schémas : `contracts/decision_support/` ; tests et fixtures : `tests/decision_support/`.
- Vue : `web/decision/` ; preuves : `evidence/decision_support/` ; docs : `docs/decision_support/`.
