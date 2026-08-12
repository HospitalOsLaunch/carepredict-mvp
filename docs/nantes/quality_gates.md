# Qualité & garde-fous — Nantes v0.1 (contexte santé)

Ce dépôt vise un livrable **impeccable en review DSI**. Le modèle qui écrit le code
n'en est pas la garantie — le **harnais** ci-dessous l'est. Il s'applique à *chaque*
ticket, quel que soit l'auteur ou le modèle.

## Les quatre garde-fous

1. **Revue AAA adverse (bloquante).** Trois relecteurs indépendants — Head of
   Engineering, Head of Product, Head of ML — relisent chaque ticket de façon
   hostile et doivent prononcer **GO**. Les findings bloquants sont traités puis
   re-confirmés avant validation. C'est ce filet qui attrape les erreurs qu'un seul
   auteur (humain ou modèle) laisse passer.

2. **Gates déterministes en CI (bloquantes).**
   - `quality` : full stack (`ruff`, `mypy --strict`, `pytest --cov`, `docker compose build`).
   - `gate-a-safety` : couche de sécurité Nantes (schéma canonique, preflight,
     validator) — lint + format + `mypy --strict` + tests offline + **couverture ≥ 95%**.
     Rapide, sans dépendances lourdes ; c'est le feu vert lisible par la DSI.

3. **Pre-commit** (`.pre-commit-config.yaml`) : `ruff` (lint+format) et `mypy --strict`
   sur la couche sécurité avant chaque commit. Le code non-clean ne peut pas entrer.

4. **Dossier de review DSI** (`dsi_review_pack_template.md`) + **template de PR** :
   chaque livraison est auto-portante (preuves d'exécution, PII/fuite/rollback, AAA)
   → la DSI valide en lecture.

## Definition of Done (rappel)

Un ticket n'est *Done* que si : critères d'acceptation prouvés ; `ruff` 0 + `mypy
--strict` clean + tests (cas négatifs et fail-closed) sur le code ajouté ; CI verte ;
provenance à jour ; périmètre timeboxé ; AAA = GO ; blockers et prochaine tâche
débloquée explicités.

## Principes non négociables (santé)

- **Fail-closed** : privacy, temporal-leakage — tout ce qui n'est pas prouvé valide est rejeté.
- **Aucune donnée nominative / texte libre** dans logs, fixtures ou rapports.
- **Aucune réparation silencieuse** des données ; pas de downgrade critique → warning.
- **Provenance** : toute sortie reliée à `run_id` + `schema_version`.
- **Offline** : la chaîne pilote s'exécute sans réseau sortant.
- **Aucune revendication causale** pour une simulation.
- **Déterminisme & reproductibilité** : même entrée → même sortie ; timestamps de référence estampillés.

## Commandes locales

```bash
pip install pre-commit && pre-commit install         # une fois
pre-commit run --all-files                           # tout le dépôt

# Couche sécurité Nantes (ce que rejoue gate-a-safety) :
ruff check services/connectors/schemas/canonical_schema.py services/validation/preflight.py services/validation/validator.py
mypy --strict services/connectors/schemas/canonical_schema.py services/validation/preflight.py services/validation/validator.py
pytest tests/unit/test_canonical_schema_v1.py tests/unit/test_preflight.py tests/unit/test_validator_v2.py \
  --cov=services.connectors.schemas.canonical_schema --cov=services.validation.preflight --cov=services.validation.validator \
  --cov-fail-under=95
```
