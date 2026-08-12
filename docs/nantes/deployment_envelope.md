# Nantes v0.1 — Enveloppe de déploiement offline en enclave CHU (HOS-004)

- **Version** : 1.0.1 · **Artefact source** : `deploy/nantes/deployment_envelope.yaml`
- **Cible** : pilote Nantes v0.1, machine unique en enclave CHU, **air-gapped (aucun réseau sortant)**.
- **Runtime** : `docker compose` v2 (compatible podman-compose) · **OS** : Ubuntu 22.04/24.04 LTS ou RHEL 9.
- **Owner** : Lead Dev · **Dépend de** : HOS-001 (ADR-0001).

> Ce document décrit la **cible enclave**. Le `docker-compose.yml` du dépôt est un compose de
> **développement** ; la section §8 « Durcissement de release » liste les écarts à appliquer (gates de
> release), vérifiés contre le compose réel.

## 1. Réseau — aucun accès Internet en exécution nominale

- **Outbound : none.** La chaîne pilote n'appelle aucun service tiers. Aucune clé d'API externe.
- **Confidentialité** : assurée par l'**air-gap + l'isolation du host**. Le trafic inter-conteneurs est **en
  clair** (pas de TLS interne, Kafka `PLAINTEXT`, MLflow http) — il n'y a pas de chiffrement en transit ;
  c'est l'enclave qui protège.
- **Exposition des ports** : le compose dev publie en syntaxe courte (`PORT:PORT`) → binding **0.0.0.0**. La
  cible enclave binde en **127.0.0.1** et **n'expose pas** les datastores au host (§3, §8).
- Images **préchargées hors ligne** (`docker save`/`load`) — aucun pull au démarrage.

## 2. Dimensionnement CPU / RAM / GPU / disque

| Profil | CPU | RAM | Disque | GPU |
|---|---|---|---|---|
| Minimal | 8 cœurs | 16 Go | 100 Go | aucun |
| Recommandé | 16 cœurs | 32 Go | 250 Go | optionnel (inférence CPU par défaut) |

Forecast v2 (JEPA/RSSM) et world model tournent en **inférence CPU** ; le GPU n'est pas requis pour le pilote.

## 3. Ports

| Service | Port host | Exposition dev (actuel) | Exposition cible enclave |
|---|---|---|---|
| API (FastAPI) | 8000 | 0.0.0.0 | 127.0.0.1 |
| Dashboard | 5173 | 0.0.0.0 | 127.0.0.1 |
| Dagster webserver | 3000 | 0.0.0.0 | 127.0.0.1 |
| MLflow | 5000 | 0.0.0.0 | 127.0.0.1 |
| TimescaleDB | 5432 | 0.0.0.0 | aucun mapping host (réseau docker interne) |
| Dagster Postgres | 5433 | 0.0.0.0 | aucun mapping host |
| Redis | 6379 | 0.0.0.0 | aucun mapping host |
| Redpanda (Kafka) | 19092 · admin 9644 | 0.0.0.0 | aucun mapping host |

Services additionnels du compose : **redpanda-init** (création one-shot des topics `sih.raw`/`fhir.raw`/
`csv.raw`/`canonical.events`, réutilise l'image redpanda) et **dagster-daemon** (réutilise l'image dagster).

## 4. Secrets

Variables d'environnement (jamais en clair dans l'image). `.env.example` embarque des **défauts de
développement en clair** (`carepredict_dev_password`, `dagster_dev_password`) qui **doivent être overridés** en
enclave :

| Variable | Portée |
|---|---|
| `POSTGRES_PASSWORD` | TimescaleDB |
| `DAGSTER_POSTGRES_PASSWORD` | Dagster Postgres |

MLflow utilise **SQLite** (`/mlflow/mlflow.db`) — pas de mot de passe DB. **Aucune clé d'API externe.**

## 5. Données persistées, localisation, rétention

| Volume | Contenu | Rétention |
|---|---|---|
| `timescaledb-data` | UnitState + séries opérationnelles (agrégats par unité) | durée du pilote + purge validée DPO |
| `dagster-postgres-data` | métadonnées d'orchestration (runs) | durée du pilote |
| `mlflow-data` | artefacts/param modèles + SQLite MLflow, provenance `run_id` | durée du pilote |
| `dashboard-node-modules` | dépendances build front (non sensible) | éphémère |
| `carepredict-artifacts` *(à ajouter en release)* | rapports/manifests pipeline | durée du pilote |

**Note importante** : le compose dev n'a **pas** de volume dédié aux artefacts pipeline — écrits sous `/app`,
ils atterrissent dans le host bind-monté. La release doit ajouter un **volume nommé dédié** (§8).

Aucune donnée nominative n'est persistée (agrégats par unité, Canonical Schema v1). **DPO** : chiffrement
disque **at-rest** des volumes vifs requis (à confirmer DSI), résidence en enclave (France) ; le champ
`avg_seniority_months` (sensibilité *restricted*, non nominatif) peut persister.

## 6. Digest, sauvegarde, rollback

- **Digest** : figer chaque image par **digest sha256** dans le compose de release + **manifest signé**. Le
  compose dev utilise des **tags** → le pin des digests est un **gate de release**. `docker compose pull`
  interdit au runtime (images préchargées).
- **Sauvegarde** : `pg_dump` TimescaleDB + Dagster-Postgres + copie des volumes `mlflow-data`/
  `carepredict-artifacts`, **chiffrés au repos**.
- **Rollback** : revenir au manifest de release N-1 (digests N-1) — `docker compose down` puis `up` sur le
  compose épinglé N-1 ; restaurer les dumps si migration de schéma (marqueur de migration à tracer dans le
  runbook HOS-023).

## 7. Hors périmètre (HOS-004)

Provisionnement réel de l'infrastructure Nantes ; haute disponibilité multi-site. Le runbook pas-à-pas
d'installation/diagnostic/rollback est livré séparément en **HOS-023**.

## 8. Durcissement de release (écarts compose dev → enclave, gates vérifiés)

1. **Épingler les images par digest sha256** (le compose dev utilise des tags).
2. **Retirer les bind-mounts `.:/app`** (api, dagster-webserver, dagster-daemon) et `./services/dashboard:/app`
   — **cuire le code dans l'image**. Sans cela, le rollback-par-digest est **illusoire** (le code s'exécute
   depuis le host, pas l'image figée).
3. **Binder les ports host en `127.0.0.1`** ; **retirer les mappings host** des datastores
   (timescaledb/redis/redpanda/dagster-postgres) — accès uniquement via le réseau docker interne.
4. **Ajouter un volume nommé dédié** aux artefacts pipeline (`carepredict-artifacts`).
5. **Overrider tous les secrets par défaut** de `.env.example` ; interdire les mots de passe de dev.
