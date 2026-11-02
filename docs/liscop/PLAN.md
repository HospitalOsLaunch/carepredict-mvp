# Plan : HospitalOS × LISCOP / ARS

Applique `docs/liscop/SPEC.md` (validée le 1er novembre 2026). Ce fichier est le
**contrat** entre les agents : noms de tables, de colonnes, de fichiers, et qui possède
quoi. Un agent ne modifie que les fichiers qui lui sont attribués ; s'il lui faut autre
chose, il le note dans son rapport au lieu de le faire.

## Phases

| Phase | Agent | Branche | Après |
|---|---|---|---|
| 0. Socle | `foundation` | `feat/liscop-0-foundation` | — |
| 1a. Mouvements | `movement-ingest` | `feat/liscop-1-movements` | 0 |
| 1b. Lits et urgences | `beds-ed` | `feat/liscop-1-beds-ed` | 0 |
| 1c. Prévision | `forecast-engine` | `feat/liscop-1-forecast` | 0 |
| 2. Export ROR / ORU | `ror-oru-export` | `feat/liscop-2-export` | 1a, 1b, 1c fusionnées |
| 3. Revue | `code-reviewer`, `security-auditor`, `test-engineer` | — (rapports) | 2 |
| 4. Corrections, simplification, livraison | `finisher` | `feat/liscop-ars` | 3 |

Chaque agent travaille dans son propre worktree (`/home/claude/wt-liscop-<nom>`), commite
sur sa branche, ne pousse pas. L'intégration (`feat/liscop-ars`) fusionne les branches.

## Contrat de données (migration `0003`, `down_revision = "0002"`)

Fichier : `services/admissions_smr/migrations/versions/0003_liscop.py`. Tout le schéma des
cinq modules est créé ici, une seule fois, par `foundation`.

### Colonnes ajoutées

`sites` : `ght` (str 120, null), `departement` (str 3, null), `territory` (str 120, null : TAS).

`bed_pools` (une unité = site × code d'unité ; la colonne `mention` porte le code d'unité,
SMR ou MCO) :
- `unit_type` (str 30, défaut `smr`) : `smr`, `medecine`, `chirurgie`, `soins_critiques`,
  `urgences`, `perinatalite`, `sante_mentale`, `medico_social`.
- `discipline` (str 30, défaut `smr`) : les 7 disciplines LISCOP (`soins_critiques`,
  `perinatalite`, `chirurgie`, `medecine`, `sante_mentale`, `smr`, `medico_social`).
- `label` (str 120, null), `uf_code` (str 20, null : unité fonctionnelle du SI),
  `ror_unit_id` (str 64, null), `extra_beds` (int, défaut 0 : lits supplémentaires
  ouverts), `crisis_reserved_beds` (int, défaut 0 : réservés crise / SSE).

`stays` :
- `bed_id` (FK `beds.id`, null), `source` (str 20, défaut `saisie` : `saisie`, `hl7`,
  `agent`, `import`), `encounter_ref` (str 64, null : HMAC du NDA), `patient_sex`
  (str 1, null : `F`, `M`, `U`), `patient_age` (int, null), `admitted_at` (datetime, null),
  `discharged_at` (datetime, null), `admission_mode` (str 20, null : `urgences`,
  `programme`, `mutation`, `transfert`).
- Index unique partiel souhaité sur (`group_id`, `encounter_ref`, `site_id`, `mention`)
  quand `encounter_ref` n'est pas nul ; à défaut, contrôle applicatif.

### Tables créées

`beds` : `id`, `group_id`, `site_id`, `pool_id` (FK `bed_pools`), `room` (str 40),
`label` (str 40), `sex_constraint` (str 1 : `F`, `M`, `X` = indifférencié),
`isolation` (bool), `status` (str 20 : `libre`, `occupe`, `a_nettoyer`, `bloque`,
`reserve`), `status_reason` (str 200, null), `stay_id` (FK `stays`, null), `active`
(bool), `updated_at`. Unique (`site_id`, `label`).

`movements` (journal des mouvements reçus ; jamais le message brut) : `id`, `group_id`,
`source_system` (str 60), `message_control_id` (str 60 : MSH-10), `movement_ref`
(str 60, null : ZBE-1), `event` (str 7 : `A01`…), `action` (str 10 : `INSERT`, `UPDATE`,
`CANCEL`), `occurred_at`, `encounter_ref` (str 64), `patient_ref` (str 64 : HMAC de l'IPP),
`site_id` (null), `pool_id` (null), `bed_id` (null), `status` (str 20 : `applied`,
`duplicate`, `cancelled`, `rejected`, `ignored`), `error` (text, null), `message_digest`
(str 64 : SHA-256), `received_at`. Unique (`group_id`, `source_system`,
`message_control_id`).

`ed_visits` : `id`, `group_id`, `site_id`, `encounter_ref` (str 64), `patient_ref`,
`arrived_at`, `admit_decision_at` (null), `left_at` (null), `outcome` (str 20, null :
`hospitalise`, `sortie`, `transfert`, `fugue`, `deces`), `target_pool_id` (null),
`source` (str 20). Unique (`group_id`, `encounter_ref`).

`ed_snapshots` : `id`, `group_id`, `site_id`, `at`, `present`, `waiting_bed` (décision
d'hospitalisation sans lit), `boarding` (lits brancards), `hosted_elsewhere`
(hébergés hors unité cible), `source` (`calcul` ou `declaration`), `declared_by` (FK
users, null), `comment` (null).

`tension_declarations` : `id`, `group_id`, `site_id` (null = établissement), `kind`
(`het`, `plan_blanc`), `level` (str 20), `started_at`, `ended_at` (null), `declared_by`,
`comment`.

`forecast_runs` : `id`, `group_id`, `created_at`, `as_of` (date), `model_version`,
`horizon_days`, `status` (`ok`, `failed`), `params_json`, `metrics_json`.

`forecast_values` : `id`, `run_id`, `site_id` (null), `pool_id` (null), `scope`
(`unit`, `site`, `group`, `ght`, `departement`), `scope_key` (str 120), `target`
(`arrivals`, `discharges`, `available_beds`, `tension_prob`, `boarding_10h`), `day`,
`mean`, `q10`, `q50`, `q90`, `p_tension` (null), `p_critique` (null). Index (`run_id`,
`target`, `day`).

`ror_outbox` : `id`, `group_id`, `created_at`, `kind` (`ror_capacity`, `oru_indicators`),
`payload_json`, `digest`, `status` (`simulated` seulement tant que non habilité).

## Fichiers attribués

| Agent | Possède (création ou modification) |
|---|---|
| `foundation` | `models.py`, `migrations/versions/0003_liscop.py`, `vocab.py`, `seed_mco.py` (nouveau), `cli.py` (commande `seed-demo-mco`), `main.py`, `config.py` (secret de pseudonymisation), stubs vides : `api/routes_{beds,ed,hl7,forecast_store}.py`, `schemas_liscop.py`, web : `App.tsx` (routes et menu), stubs `pages/{BedBoard,Urgences,Prevision}Page.tsx`, `api/types_liscop.ts` ; `tests/test_migrations.py` si besoin |
| `movement-ingest` | `domain/hl7_pam.py`, `domain/pseudonym.py`, `api/routes_hl7.py`, `tests/test_hl7_*.py`, `tests/fixtures/hl7/*`, `services/admissions_agent/demo_bedsoft/`, `services/admissions_agent/playbooks/demo_bedsoft.yaml`, ajouts dans `services/admissions_agent/playbook.py`/`runner.py` pour la tâche `sync_movements`, `tools/his_simulator.py` |
| `beds-ed` | `domain/beds.py`, `domain/ed.py`, `domain/tension.py`, `api/routes_beds.py`, `api/routes_ed.py`, `tests/test_beds*.py`, `tests/test_ed*.py`, web `pages/BedBoardPage.tsx`, `pages/UrgencesPage.tsx`, tests web associés |
| `forecast-engine` | `services/forecast_engine/` (tout), `api/routes_forecast_store.py`, `tests/` du paquet, web `pages/PrevisionPage.tsx` + test, `docs/liscop/BACKTEST.md` |
| `ror-oru-export` | `domain/ror.py`, `api/routes_ror.py`, `tests/test_ror_export.py`, web `pages/RorPage.tsx` + test |
| tous | ajouts (append) dans `schemas_liscop.py` et `api/types_liscop.ts`, chacun dans sa propre section commentée |

## Démo MCO (`seed-demo-mco`)

Groupe « Centre hospitalier des Deux-Rivières (fictif) », département 59, GHT fictif
« GHT Hainaut-Fictif ». Sites : « CH Deux-Rivières » (MCO + urgences) et « SMR Les Saules »
(SMR). Unités : urgences, médecine polyvalente, court séjour gériatrique, cardiologie,
chirurgie viscérale, chirurgie orthopédique, réanimation (soins critiques), SMR
polyvalent, SMR gériatrie. Chambres simples et doubles (sexe, isolement), environ 250 lits.
Un an d'historique : passages aux urgences (environ 120 par jour, saisonnalité hebdomadaire
et annuelle, épisode épidémique hivernal), décisions d'hospitalisation, séjours avec lit,
mutations, sorties, fermetures de lits. Comptes `bedmanager@`, `cadre@`, `direction@`,
`admin@`, `agent@` sur `ch-demo.hospitalos.fr`, mot de passe `demo-hospitalos-2026`.
Aucune identité réelle, aucune donnée identifiante.

## Règles communes

- Lire `docs/liscop/SPEC.md` et ce plan avant de commencer.
- Compétences à utiliser : `incremental-implementation`, `test-driven-development`,
  `source-driven-development`, `security-and-hardening`, `ponytail` (et
  `frontend-ui-engineering` pour l'interface).
- Graphe du code : `/home/claude/venv-graphify/bin/graphify query "<question>" --graph
  /home/claude/carepredict-mvp/graphify-out/graph.json`.
- Environnement Python : `/home/claude/venv-smr` (statsforecast, holidays, hl7 installés).
  Navigateur : `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`.
- Avant chaque commit : `pytest -q`, `ruff check services tools`, `ruff format --check
  services tools`, `mypy --config-file services/admissions_smr/mypy.ini ...`, et pour le web
  `npm test && npm run build`.
- Aucune donnée identifiante stockée ; aucun appel réseau sortant ; aucun push.
