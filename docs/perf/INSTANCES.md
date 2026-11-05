# Plusieurs processus et plusieurs conteneurs pour l'API

Règle 28 de l'audit de performance. Un processus Python ne fait qu'un calcul à la fois :
avec une seule instance, la prévision (90 à 170 ms) d'un gestionnaire de lits fait
attendre le cadre qui ouvre le plan des lits au même moment. Et si ce processus meurt,
plus rien ne répond.

## Ce qui est en place

| Niveau | Comment | Réglage |
|---|---|---|
| Processus, dans un conteneur | `python -m services.admissions_smr.serve` (CMD de l'image) lance plusieurs processus uvicorn ; un processus qui meurt est relancé, les autres répondent | `ADM_API_WORKERS` (par défaut, les cœurs de la machine, entre 2 et 4) |
| Conteneurs | `docker compose up --scale api=3` : nginx répartit les appels sur toutes les adresses de `api` trouvées à son démarrage, écarte 10 s une instance qui échoue trois fois, et relance une seule fois une lecture sur une autre instance (une écriture n'est jamais envoyée deux fois) | `upstream hospitalos_api` dans `nginx.conf` |
| Migrations | Chaque processus met le schéma à jour au démarrage. Sur PostgreSQL, un verrou (`pg_advisory_xact_lock`) fait migrer le premier ; les autres attendent puis trouvent le schéma à jour | `migrate.py` |

Rien n'est gardé en mémoire d'un appel à l'autre qui suppose un seul processus : la
session est un jeton signé, la connexion OIDC passe par un cookie signé, le verrou
d'écriture d'un groupe est dans la base.

Limites :

- **SQLite** (développement seulement) garde un seul processus : la base n'accepte qu'un
  écrivain.
- **Nombre de conteneurs :** nginx lit les adresses de `api` à son démarrage. Après un
  `--scale` qui change ce nombre, il faut recharger nginx :

  ```bash
  docker compose exec web nginx -s reload
  ```
- **Connexions PostgreSQL :** chaque processus garde jusqu'à 15 connexions (pool de
  SQLAlchemy). 4 processus × 3 conteneurs donnent 180 connexions, au-delà des 100 de
  PostgreSQL par défaut : il faut alors réduire `ADM_API_WORKERS` ou augmenter
  `max_connections`.

## Mesures (4 novembre 2026)

Démo LISCOP chargée dans PostgreSQL 16, machine de 4 cœurs. 16 personnes en même temps
pendant 20 s, sur le mélange d'appels de l'écran d'un gestionnaire de lits (tableau de
bord, plan des lits, urgences, demandes, patients présents).

| API | Appels par seconde | Attente médiane | p95 | Erreurs |
|---|---|---|---|---|
| 1 processus | 11,4 | 1 597 ms | 2 188 ms | 0 |
| 4 processus | 32,4 | 188 ms | 1 664 ms | 0 |
| 4 processus, l'un tué en pleine charge | 28,4 | 314 ms | 1 766 ms | 0 (relancé par uvicorn) |

Démarrage simultané de quatre processus sur une base vide : sans le verrou, trois sur
quatre s'arrêtaient sur une erreur de clé dupliquée en créant les tables ; avec le verrou,
les quatre démarrent (test `test_serve.py`, joué sur PostgreSQL en CI). La CI démarre aussi
deux conteneurs d'API derrière le vrai nginx.
