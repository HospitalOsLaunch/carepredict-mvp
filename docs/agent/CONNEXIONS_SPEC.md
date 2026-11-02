# Spec : piloter le computer use depuis l'interface de chaque hôpital

Statut : décisions validées le 2 novembre 2026 (identifiants chiffrés côté HospitalOS ;
l'administrateur paramètre, la coordination pilote). Branche d'intégration
`feat/agent-connections` (depuis `mvp/computer-use`).

## Objectif

Aujourd'hui, l'adresse du logiciel lu, ses identifiants, le script (playbook) et les
tâches sont des variables d'environnement du poste agent ; un seul agent par groupe.
Demain, le poste agent n'a plus besoin que de trois choses (adresse de l'API, compte
`ingestion`, nom du poste) ; **tout le reste se lance, se met en pause et se paramètre
dans HospitalOS**, établissement par établissement (site), par des utilisateurs habilités.

## Concepts

- **Poste agent** (`agent_workers`) : une machine du réseau de l'hôpital qui exécute
  l'agent. Identifiée par `agent_id` dans son groupe ; s'enregistre au premier signal ;
  déclare sa version, ses moteurs et son **catalogue de scripts** (playbooks embarqués,
  avec type et tâches). Plusieurs postes par groupe.
- **Connexion** (`agent_connections`) : un logiciel à lire pour un site. Champs :
  `name`, `kind` (`portail_orientation` ou `gestion_lits`), `site_id` (null = tout le
  groupe), `url`, `allowed_hosts` (hôte de l'URL + liste en plus), `username`,
  **secret chiffré** (écriture seule), `playbook` (nom choisi dans le catalogue d'un
  poste), `tasks` (`sync_inbox` et `reply_portal` pour un portail ; `sync_movements`
  pour la gestion des lits), `source_system` (gestion des lits : doit figurer dans
  `users.allowed_sources` du compte du poste, ajouté automatiquement à l'enregistrement),
  planning (`interval_minutes`, plage horaire `active_from`–`active_to`, jours), poste
  assigné (`agent_id`, null = tout poste du groupe dont le catalogue contient le script),
  état (`arretee`, `active`, `en_pause`), dernier passage, prochain passage, dernier
  résultat, dernière erreur (sans aucune valeur lue à l'écran).
- **Pause générale** du groupe (existante, `agent_states.paused`) : arrête tout, prime sur
  l'état des connexions.
- Les tâches (`agent_tasks`) portent `connection_id` ; une réponse à reporter
  (`reply_portal`) va à la connexion portail active du site de la demande.

## Commandes et droits

| Action | admin_groupe | coordination | direction |
|---|---|---|---|
| Créer, modifier, archiver une connexion ; saisir ou effacer un secret ; assigner un poste ; routage, budgets | oui | non | non |
| Démarrer, mettre en pause, reprendre, relever maintenant | oui | oui, sur les connexions de son site (et toutes si non limitée à un site ; les connexions « tout le groupe » : non limitée seulement) | non |
| Pause / reprise générale | oui | non | non |
| Voir postes, connexions, passages, tâches à reprendre | oui | oui (son périmètre) | oui (lecture) |

Chaque commande est auditée (jamais le secret ; « secret modifié » seulement).

## Sécurité des identifiants

- Chiffrement AES-256-GCM (`cryptography`, déjà présent via `pyjwt[crypto]`), clé par
  groupe dérivée par HKDF-SHA256 d'une clé maître `ADM_CONNECTOR_KEY` et du `group_id`,
  but « connector » ; préfixe de version (`v1:`) pour la rotation ; données associées
  (AAD) = `group_id|connection_id` pour qu'un secret ne puisse pas être recollé sur une
  autre connexion.
- `ADM_CONNECTOR_KEY` obligatoire hors `ADM_ENV` ∈ {development, test} (même règle que les
  autres clés : longueur minimale, différente des autres secrets).
- L'API ne renvoie jamais le secret à l'interface (`secret_set`, `secret_updated_at`
  seulement). Il est déchiffré **uniquement** dans la réponse de réservation d'une tâche,
  pour un compte `ingestion` du même groupe, sur une connexion active ; le poste le garde
  en mémoire le temps de la tâche, ne l'écrit ni ne le journalise, et le script se
  connecte (aucun modèle ne voit les identifiants — règle existante).
- URL : https exigé hors réseau interne explicite (même règle que `AGENT_API_URL`) ; la
  navigation reste bornée aux `allowed_hosts` de la connexion.
- Scripts : choix dans le catalogue embarqué du poste uniquement (pas de téléversement de
  script depuis l'interface).

## Contrat d'API

Interface (préfixe `/api/agent`) :

- `GET /workers` → `[{agent_id, site_id, online, last_heartbeat_at, version, engines:
  [{name, configured, detail}], playbooks: [{name, label, kind, tasks}]}]`
- `GET /connections` → `[ConnectionOut]` ; `ConnectionOut` = `{id, name, kind, site_id,
  site_name, url, allowed_hosts, username, secret_set, secret_updated_at, playbook, tasks,
  source_system, interval_minutes, active_from, active_to, days, agent_id, status,
  last_run_at, next_run_at, last_outcome, last_error, pending_tasks, needs_human,
  can_control, can_edit}`
- `POST /connections` (admin) ← `{name, kind, site_id?, url, allowed_hosts?, username?,
  secret?, playbook, tasks, source_system?, interval_minutes, active_from?, active_to?,
  days?, agent_id?}` → 201 `ConnectionOut` (état initial `arretee`)
- `PATCH /connections/{id}` (admin) ← champs partiels ; `secret` remplace, `clear_secret:
  true` efface
- `DELETE /connections/{id}` (admin) → archive (plus listée, tâches en attente annulées)
- `POST /connections/{id}/start|pause|resume` (admin ou coordination habilitée)
- `POST /connections/{id}/sync` → tâche créée maintenant (refus si arrêtée ou pause
  générale)
- `GET /connections/{id}/runs?limit=20` → derniers passages (tâches) sans valeur d'écran
- Existant, conservé : `GET /status`, `PUT /policy`, `POST /pause`, `POST /resume`,
  `GET /tasks`, `POST /tasks/{id}/retry|manual`.

Poste agent :

- `POST /heartbeat` ← ajoute `playbooks` (catalogue) ; → ajoute `connections:
  [{id, kind, playbook, tasks, status, interval_minutes, active_from, active_to, days,
  next_run_at}]` (sans secret ni identifiant) assignées ou assignables à ce poste.
- `POST /tasks/claim` → chaque tâche porte `connection: {id, url, allowed_hosts,
  username, secret, playbook, source_system}` (secret déchiffré, seulement ici).
- La planification est faite **côté API** (prochain passage calculé, tâche créée au
  signal du poste quand elle est due et dans la plage horaire) ; le poste ne décide plus
  du rythme.
- Mode historique conservé : si aucune connexion n'existe et que `AGENT_PORTAL_URL` est
  défini, le poste se comporte comme aujourd'hui (une connexion implicite).

## Interface

Nouvel écran « Computer use » dans le menu (admin, coordination, direction) :

- en tête : pause générale (admin), postes (en ligne / hors ligne, version, moteurs,
  dernier signal) ;
- une carte par connexion : nom, site, logiciel, état (puce), boutons **Démarrer**,
  **Mettre en pause**, **Reprendre**, **Relever maintenant** selon les droits, dernier et
  prochain passage, tâches à reprendre, dernière erreur ; historique des passages ;
- admin : créer / modifier une connexion (type, site, URL, identifiant, mot de passe en
  écriture seule avec « défini le … » et « effacer », script choisi dans le catalogue des
  postes, tâches, planning, poste), lien vers le routage et les budgets existants
  (Paramètres → Agent et routage) ;
- microcopies françaises, jetons de design existants, accessible, responsive.

## Démo

- Les deux jeux de démonstration créent leurs connexions (portail fictif pour le groupe
  SMR, logiciel de gestion des lits fictif pour le CH MCO), démarrées.
- `docker-compose.demo.yml` : services `agent` (SMR) et `agent-mco` + `bedsoft` (logiciel
  fictif) configurés seulement avec adresse de l'API, compte et nom du poste.
- `tools/demo_check.py` : démarrer / mettre en pause une connexion par l'API et vérifier
  l'effet.

## Critères de réussite

1. Un administrateur crée une connexion, saisit un mot de passe, la démarre : le poste
   (sans autre configuration locale) relève à l'intervalle prévu, dans la plage horaire.
2. Pause d'une connexion : plus aucune tâche créée ni réservée pour elle ; reprise :
   reprend. Pause générale : tout s'arrête.
3. Un cadre limité à un site pilote ses connexions et pas celles d'un autre site ; la
   direction lit seulement ; un autre groupe ne voit rien (404).
4. Le secret n'apparaît jamais dans une réponse d'interface, un journal, l'audit ou une
   erreur ; il est illisible en base sans la clé ; un secret ne se déchiffre pas sur une
   autre connexion.
5. Mode historique (variables d'environnement) toujours fonctionnel.
6. Tous les contrôles verts (pytest, ruff, mypy, vitest, build) ; démo vérifiée.
