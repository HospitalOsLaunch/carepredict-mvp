# Environnement de référence (verrouillé)

Un seul environnement Python sert au produit (cockpit hybride, planificateur 24 h), à la fondation
synthétique, aux services, aux modèles de recherche et aux tests : **`requirements.lock`**, avec versions
exactes et empreintes SHA-256.

## Installer

```bash
python3.11 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.lock   # torch CPU depuis download.pytorch.org
.venv/bin/pip install --no-deps -e .
PYTHONPATH=src:. .venv/bin/python -m pytest -q                # suite par défaut
```

Versions clés : Python 3.11 ; torch 2.15.0+cpu ; numpy 2.4.6 ; scipy 1.17.1 ; scikit-learn 1.8.0 ;
pandas 2.3.3 ; pydantic 2.14 ; fastapi 0.165. Ce sont les versions avec lesquelles les checkpoints et
pickles de recherche (HOWM, INT-1, P5) ont été produits.

Toutes les workflows CI installent ce fichier, sauf deux exceptions voulues :

- `gate-a-safety` (porte de sécurité Nantes) reste volontairement minimale et autonome ;
- `platform-typecheck` installe les versions exactes de l'image Dagster.

## Régénérer le verrou

Après modification des dépendances de `pyproject.toml` :

```bash
uv pip compile pyproject.toml --extra dev --python-version 3.11 \
  --python-platform x86_64-unknown-linux-gnu \
  --extra-index-url https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match \
  --generate-hashes --emit-index-url --no-header -o requirements.lock
```

Puis reconstruire un venv neuf depuis le verrou et relancer toute la suite.

## Hors du verrou

| Extra | Contenu | Où il tourne | Pourquoi |
|---|---|---|---|
| `platform` | Dagster, dbt, Feast, Great Expectations | image `infrastructure/dagster/Dockerfile` (versions exactes) | Feast 0.40 et GE 0.18 exigent numpy < 2 ; les résultats de recherche utilisent numpy 2 |
| `foundation` | pytorch-forecasting, uni2ts | non installé par défaut | anciens wrappers TFT/Moirai ; uni2ts n'a pas de version publiée figée |

## Version exacte de Python

`.python-version` et les images Docker restent en **3.11.9**, version de référence de l'audit du
planificateur (porte ouverte : 3.11.9 non disponible dans les environnements d'exécution utilisés,
où 3.11.18 a servi). Le verrou est compatible avec tout Python 3.11.

## Qualité : périmètres

- **Ruff** : tout le dépôt, sauf le code de recherche sous gel (empreintes enregistrées dans les
  gels et registres de campagne : le reformater casserait les contrôles de gel) ; liste dans
  `[tool.ruff] extend-exclude` de `pyproject.toml`.
- **mypy --strict** : `services`, `data`, les tests produit et ML (`tests/unit`, `integration`, `e2e`,
  `hybrid`, `operational`, `tests/test_*.py`) ; `src/hospitalos/hybrid` et `tests/hybrid` dans leur
  workflow ; `src/hospitalos/synthetic` dans le sien.
- **Dette restante** : `src/hospitalos/decision_support` et `tests/decision_support` ne passent pas
  `mypy --strict` (environ 365 erreurs, porte déjà ouverte dans le reçu de clôture v6) ; le code de
  recherche gelé n'est pas typé strictement.

## État vérifié (23 novembre 2026, venv neuf créé depuis le verrou)

| Contrôle | Résultat |
|---|---|
| `pytest` (suite par défaut) | 1 371 réussis, 10 ignorés |
| Tests des campagnes de recherche (`scripts/filter_*`, `action_effects`, `plan48`) | 29 réussis |
| Tests `services/` | 60 réussis, 17 ignorés |
| Cockpit web (Vitest) | 72/72 |
| `ruff check .` | aucun écart |
| `mypy --strict` (périmètre CI) | aucun écart |
