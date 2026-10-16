# HOS-000 — Repo Map & Commandes Canoniques (Nantes v0.1)

- **Date** : 2026-08-11
- **Branche de base** : `main` (branche par défaut)
- **Commit SHA cartographié** : `a72738299a0a1b949b71428d4bceae02cb2582e1` (`a727382`)
- **Périmètre** : reconnaissance seule. Aucun code métier modifié (conforme au hors-périmètre HOS-000).
- **Source de vérité des commandes** : `.github/workflows/ci.yml` + `Makefile` + `pyproject.toml`.
- **Revu par** : Head of Engineering, Head of Product, Head of ML (findings intégrés — cf. §8).

> **Choix de branche prouvé (nuance post-revue)** : `main` est la **ligne d'intégration la plus complète**
> (rs_jepa + ts_jepa + stack serving + baselines gelées) — mais **pas un surensemble strict**.
> `main` est +34 commits devant `v3-MTS-JEPA-federated` et `(Finale)-v3-MTS-JEPA-federated`, tout en étant
> −10 / −1 derrière : les branches JEPA portent des fichiers **net-new absents de `main`**
> (`src/forecasting/make_figures.py`, `tests/test_mts_jepa_federated.py`, `docs/mts_jepa_federated.md`,
> `.github/workflows/forecasting.yml`, `requirements-forecasting.txt`, `conftest.py`) = le **forecaster
> MTS-JEPA fédéré**, qui relève de **Gate B** (différable après sign-off Gate A). `research/gate1b-aval`
> = `main` +8 commits ajoutant uniquement `research/clin-jepa-gate1b/` (embeddings Qwen = Gate B).
> **Verdict** : baser S1→Gate A sur `main` ; le forecaster fédéré et gate1b restent des pistes Gate B non
> mergées, à réconcilier après sign-off. Le choix respecte l'ordre de coupe (pas de Gate B en avance).

---

## 1. Carte des modules (domaine → chemin → rôle)

| Domaine | Chemin | Rôle |
|---|---|---|
| Ingestion / connecteurs | `services/connectors/` | HL7v2 / FHIR / CSV, `normalizer.py`, schémas `schemas/canonical.py`, `schemas/hl7_messages.py` |
| Schéma canonique (existant) | `services/connectors/schemas/canonical.py` | `CanonicalBase` + `Canonical{Admission,Discharge,CareLoad,Staffing}` (Pydantic v2, `extra="forbid"`, `frozen`). Possède `received_at` (ingestion) — **≠** paire bitemporelle `event_time`/`available_at` requise par le leakage gate |
| Validation | `services/validation/` | **Quasi vide** : scaffolding Great Expectations (`great_expectations.yml`, `.gitkeep`) |
| Feature pipeline | `services/feature_pipeline/` | dbt (marts) + Feast (feature store) |
| ML — incertitude (PROD) | `services/ml/uq/conformal.py` | **`ConformalForecaster` (MAPIE) = module UQ de production**, câblé à `services/api/dependencies/model_loader.py`, `services/ml/training/{train_tft,backtesting}.py`, `tests/e2e/test_full_flow.py` |
| ML — world model (PROD, servi) | `services/ml/world_model/` | `inference.py:WorldModelService`, `rssm.py:HospitalRSSM`, `action_channels.py` — **câblé aux routers `simulate` + `actions`** (les 2 capacités phares du pilote) |
| ML — registry / training | `services/ml/{registry,training,recommend}/` | `registry/mlflow_client.py`, `training/train_tft.py`, `recommend/` |
| Forecast v2 (R&D Timescale) | `src/hospitalos/` | `dynamics/jepa_rssm.py`, `training/train_v2_forecast.py`, `eval/eval_v2.py`, `data/timescale_adapter.py` |
| Encodeur TS-JEPA | `src/hospitalos/encoders/ts_jepa/` | JEPA (encoder/predictor/masking/patcher/probes) |
| World-model RS-JEPA (R&D) | `rs_jepa/` | RSSM + action channel + heads criticité — **Gate B** |
| Baselines gelées | `src/hospitalos/eval/baseline_v1.py`, `artifacts/v1_full/`, `artifacts/baseline_v1_full.json` (+ `.sha256`) | persistence / seasonal-naive figées ; chargées par `eval_v2.py` (frozen-protocol) |
| Scripts R&D UQ (LEGACY) | `carepredict_quantile.py`, `carepredict_cqr.py`, `carepredict_ingest.py` | scripts autonomes DREES/synthétique (sklearn HGBR) — **non câblés au serving**. À ne pas confondre avec `services/ml/uq/` |
| API de serving | `services/api/` | FastAPI : `routers/{health,predict,forecast,simulate,actions,history}.py`, `main.py` |
| Dashboard | `services/dashboard/` (React/TS) + `dashboards/` (Streamlit) | UI jumeau numérique |
| Orchestration | `orchestration/dagster/`, `infrastructure/dagster/` | pipelines Dagster |
| Infra / containers | `docker-compose.yml`, `infrastructure/{api,dagster,mlflow}/Dockerfile`, `services/dashboard/Dockerfile` | stack offline (timescaledb, redpanda, feast, mlflow) |
| Tests | `tests/` (47 fichiers `.py` : `unit/`, `integration/`, `e2e/test_full_flow.py`) + `services/**/tests/` | unit → e2e |
| CI | `.github/workflows/ci.yml` | lint + type-check + tests + docker build |

---

## 2. Entrypoints par étape de chaîne

| Étape | Entrypoint(s) réel(s) | Commande |
|---|---|---|
| Seed synthétique | `data/synthetic/{siips_generator,load_synthea_to_db,mimic_loader}.py`, `generate_synthea.sh` | `make seed` |
| Ingest connecteurs | `services/connectors/{hl7v2,fhir,csv}_connector.py`, `normalizer.py`, `carepredict_ingest.py` (legacy) | *(pas de cible make câblée — à formaliser)* |
| Validation | `services/validation/` (**à durcir — HOS-006**) | *(inexistante, cf. §5)* |
| Features | `services/feature_pipeline/dbt`, `feast` | `make features` |
| Train (servi) | `services/ml/training/train_tft.py` | `make train` |
| Train (R&D v2) | `src/hospitalos/training/train_v2_forecast.py` | *(pas de cible make — décision serving HOS-001)* |
| Forecast / eval | `src/hospitalos/eval/eval_v2.py`, `src/hospitalos/eval/baseline_v1.py` | `python -m hospitalos.eval.eval_v2` |
| Serving | `services/api/main.py` (routers dont `simulate`, `actions`) | `make api` (`uvicorn services.api.main:app`) |
| Containers | `docker-compose.yml` | `make up` / `docker compose build` |
| E2E | `tests/e2e/test_full_flow.py` | `pytest tests/e2e` |

---

## 3. Commandes canoniques (alias → commande réelle → statut d'exécution)

Statuts réels constatés le 2026-08-11 dans le sandbox (offline, venv `.venv` : `pydantic numpy pytest`).

| Alias roadmap | Commande réelle (dérivée du dépôt) | Statut | Preuve / raison |
|---|---|---|---|
| `fmt` | `ruff format --check .` | ⚠️ EXÉCUTÉ — échoue | 64 fichiers seraient reformatés / 169 déjà conformes |
| `lint` | `ruff check .` | ⚠️ EXÉCUTÉ — échoue | **183 erreurs** (60 auto-fixables). Dette lint pré-existante sur `main` |
| `types` | `mypy --strict services orchestration data tests` | ⛔ NON EXÉCUTÉ | nécessite `.[dev]` complet (torch, dagster…) non installé en sandbox |
| `unit` | `pytest tests/unit -q` | 🟡 PARTIEL | `tests/unit/test_canonical_schema.py` **PASSE** (offline, venv léger). Sous-ensemble torch/db non exécuté |
| `contract` | `pytest tests/unit/test_canonical_schema.py` | ✅ EXÉCUTÉ — passe | 1 passed in 0.07s |
| `adverse` | *(aucune)* | ⛔ INDISPONIBLE | **À construire (HOS-008)** — générateur adverse 14 failure modes absent |
| `privacy` | *(aucune)* | ⛔ INDISPONIBLE | **À construire (HOS-009)** — `git grep privacy` = 0 fichier |
| `leakage` | *(gate `available_at` absente ; prior art `assert_no_temporal_leakage`)* | ⛔ INDISPONIBLE | **À construire (HOS-010)** — gate fail-closed sur `available_at` absente. Prior art à réconcilier : `carepredict_cqr.py:188 assert_no_temporal_leakage` (ordre train<calib<test) |
| `repro` | *(aucune formalisée)* | ⛔ INDISPONIBLE | **À construire (HOS-013)** — idempotence/reprise non outillée |
| `e2e` | `pytest tests/e2e/test_full_flow.py` | ⛔ NON EXÉCUTÉ | nécessite la stack docker (timescaledb/redpanda/feast) |
| `offline` | `docker compose config` puis smoke réseau désactivé | ⛔ NON EXÉCUTÉ | nécessite docker compose ; à valider en HOS-011 |

**Commandes CI authoritatives** (`.github/workflows/ci.yml`) : `ruff check .` · `mypy --strict services orchestration data tests` · `pytest --cov=services/connectors --cov=services/feature_pipeline --cov=services/ml --cov=services/api` · `docker compose config` · `docker compose build`.

---

## 4. Inventaire des composants Gate A (existe / partiel / absent)

Décomptes `git grep` = **fichiers `.py`** (le token peut apparaître aussi en `.md`/`.yml`).

| Composant Gate A | État | Preuve |
|---|---|---|
| Canonical Schema | 🟡 PARTIEL | `schemas/canonical.py` sans `event_time`/`available_at`, ni version, ni sensibilité, ni domaines `capacity`/`actions`. `received_at` présent ≠ base leakage (HOS-002) |
| Validator déterministe | ⛔ ABSENT | `services/validation/` = scaffolding GE vide (HOS-006) |
| Privacy Gate | ⛔ ABSENT | `git grep privacy` = 0 `.py` (HOS-009) |
| Temporal-Leakage Gate (`available_at`) | ⛔ ABSENT (mais prior art) | `git grep available_at` = 0. **Logique anti-fuite partielle existante** : `carepredict_cqr.py:188 assert_no_temporal_leakage` — à superséder/réconcilier, pas à ignorer (HOS-010) |
| UnitState v1 | ⛔ ABSENT | `git grep -i unitstate` = 0 (HOS-010U) |
| Forecast + incertitude | 🟢 PRÉSENT (prod) | `services/ml/uq/conformal.py:ConformalForecaster` (MAPIE), câblé serving/train/e2e. `carepredict_quantile.py` = legacy R&D |
| World model (simulate/actions) | 🟢 PRÉSENT (prod, servi) | `services/ml/world_model/` (RSSM) câblé `routers/simulate.py`+`actions.py`. **Classification Gate A/B à trancher en HOS-001** |
| Cascade d'abstention | ⛔ ABSENT | `git grep abstain` = 0 (HOS-014) |
| Baselines (persistence/seasonal) | 🟢 PRÉSENT | `baseline_v1.py`, `artifacts/v1_full/`, `baseline_v1_full.json` (+`.sha256`), chargés par `eval_v2.py` (HOS-015 = benchmark) |
| Provenance / run_id | 🟡 PARTIEL | `run_id` MLflow uniquement ; pas de chaîne extraction→UnitState→modèle→éval (HOS-012) |
| E2E offline | 🟡 PARTIEL | `tests/e2e/test_full_flow.py` existe ; exécution offline non prouvée (HOS-011) |

**Lecture** : socle **forecasting + world-model servi** mûr ; la **couche d'intégration pilote Gate A**
(validator, privacy, leakage `available_at`, UnitState, provenance de bout en bout, abstention, e2e offline)
est ce que S1→S2 doit livrer. Tout se greffe sur l'existant (`services/connectors`, `services/validation`,
`services/ml/uq`, `services/ml/world_model`, `services/api`) — **aucune architecture parallèle**.

---

## 5. Les 8 défauts NO-GO (taxonomie — source : HOS-006 « Dans le périmètre »)

| # | Défaut | Attendu Validator v2 | Présent aujourd'hui |
|---|---|---|---|
| 1 | Fichiers corrompus | NO-GO + exit code ≠ 0, aucun crash non contrôlé | ⛔ |
| 2 | Schéma (champs manquants/inconnus) | rejet, code+sévérité+localisation | ⛔ |
| 3 | Types invalides | rejet déterministe | 🟡 (Pydantic partiel sur schéma existant) |
| 4 | Valeurs hors domaine | rejet + remédiation | ⛔ |
| 5 | Timestamps (ordre, tz, futur) | rejet, lié à `event_time`/`available_at` | ⛔ |
| 6 | Doublons | détection + remédiation | ⛔ |
| 7 | Missingness | seuils, sévérité | ⛔ |
| 8 | Catégories inconnues | rejet fail-closed | ⛔ |

→ **Preuve source disponible** (taxonomie exhaustive dans HOS-006). Le ticket **ne passe pas BLOCKED**.
Fixtures + tests à livrer en HOS-006.

---

## 6. Décisions ouvertes à trancher en HOS-001 (matériel remonté par la recon)

1. **Périmètre `simulate` + `actions` dans Gate A ?** Les 2 capacités phares du pilote (« recommander des
   actions », « simuler des scénarios ») sont câblées à `services/ml/world_model/` (RSSM). Si dans Gate A,
   ce RSSM n'est pas différable et change de classification ; si hors Gate A, le pilote livre un jumeau de
   forecasting sans ces deux surfaces. **À trancher avant de geler le périmètre.**
2. **Stack de serving forecast unique** : `services/ml/training/train_tft.py` (servi, TFT+`uq/conformal`)
   vs `src/hospitalos/training/train_v2_forecast.py` (R&D JEPA/RSSM Timescale). Un seul chemin doit être
   désigné pour Gate A.
3. **UnitState v1** : propriétaire + schéma (HOS-010U) — contrat entre données canoniques et modèles.
4. **Forme de la chaîne de provenance** extraction→UnitState→modèle→éval reliée par `run_id` (HOS-012).

---

## 7. Blockers & prochaines tâches débloquées

- **AGENTS.md absent** : méthode HOS-000 impose de le lire. Constat documenté ; conventions dérivées de
  `pyproject.toml` (ruff/mypy strict, py311), `Makefile`, CI.
- **Dette qualité pré-existante sur `main`** : `ruff check` 183 erreurs, `ruff format` 64 fichiers.
  À NE PAS corriger en masse (hors périmètre S1) ; le code Gate A ajouté doit être *clean* (0 erreur ruff/mypy).
- **Chaîne débloquée par HOS-000** : HOS-001 (décisions, cf. §6), puis HOS-002 (schéma), HOS-006 (validator), HOS-007.

## 8. Revue & journal d'exécution

- **2026-08-11 — HOS-000** : dépôt cloné (`main@a727382`), 4 branches comparées (verdict `main`),
  modules & entrypoints cartographiés, commandes canoniques exécutées (fmt/lint/contract) ou marquées
  indisponibles avec raison, inventaire Gate A + 8 défauts produit.
- **2026-08-11 — Revue AAA** (Head of Eng / Product / ML) : 3× GO-WITH-CHANGES. Findings intégrés :
  verdict de branche nuancé (pas de surensemble strict) ; ajout `services/ml/world_model/` (servi) et
  `services/ml/uq/conformal.py` (UQ prod) ; distinction gate `available_at` absente vs prior art
  `assert_no_temporal_leakage` ; correction chemins/commandes (`hospitalos.eval.eval_v2`, `make seed/train`) ;
  décomptes qualifiés `.py` + tests=47 ; ajout §6 décisions HOS-001. Prochain : HOS-001.
