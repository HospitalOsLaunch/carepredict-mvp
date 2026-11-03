# Spec : voir ce que fait l'agent, en direct et en replay, dans un player

Statut : décisions validées le 2 novembre 2026. Branche `feat/agent-player` (depuis
`mvp/computer-use`).

| Décision | Choix |
|---|---|
| Identités patients | **Zones masquées sur le poste avant toute capture** ; direct et replay ; rien d'identifiant ne quitte l'hôpital ni n'est stocké |
| Conservation du replay | **7 jours** (`ADM_AGENT_REPLAY_DAYS`, défaut 7), puis purge |
| Qui regarde | **Administrateur et coordination**, dans leur périmètre de site ; direction : non ; chaque visionnage journalisé |

## Objectif

Le computer use ne doit pas être une boîte noire. Pour chaque passage de l'agent, une
personne habilitée voit **dans un player** ce qui se passe sur l'écran du logiciel :
en direct pendant la tâche, et en replay ensuite. Chaque image est accompagnée d'une
explication en français de ce que l'agent fait et pourquoi, du moteur utilisé, du
résultat, et de ce qui a été transmis à HospitalOS.

## Ce que le player montre

- **L'écran** tel que l'agent le voit, image par étape, zones identifiantes recouvertes
  d'un aplat hachuré marqué « Masqué : identité patient » (ou « Masqué : mot de passe »).
- **Le geste** : pointeur et onde de clic à l'endroit exact du clic, cadre autour du champ
  rempli, défilement indiqué.
- **La transcription** synchronisée, une ligne par étape : icône, phrase claire
  (« Ouvre la liste des mouvements du jour », « Saisit l'identifiant », « Lit 12
  mouvements », « Relit le dossier pour vérifier la réponse : conforme »), moteur
  (script, modèle ouvert, Claude), durée, résultat (réussi / échec / à reprendre).
  Aucune valeur lue à l'écran n'y figure (jamais de nom, de date de naissance, ni de
  mot de passe) ; les comptes et les codes (UF, lit, référence pseudonymisée tronquée)
  sont permis.
- **Ce qui a été transmis** à HospitalOS par étape de lecture : nombre d'éléments, champs
  (noms seulement), résultat de l'API (appliqués, doublons, refusés).
- **Les contrôles** : lecture / pause, image précédente / suivante, étape précédente /
  suivante, vitesse (1×, 2×, 4×), barre de temps avec repères d'étapes cliquables
  (couleur selon le résultat), « En direct » qui suit la dernière image, plein écran,
  raccourcis clavier (espace, flèches), accessible au lecteur d'écran (la transcription
  est la version texte du player).

## Masquage (fait sur le poste, avant capture)

- Le script (playbook) déclare une section `privacy` : sélecteurs à masquer par écran
  (`mask`) et motif (`identite`, `secret`, `autre`). Les champs `type=password` et tout
  champ rempli avec un identifiant ou un secret sont toujours masqués.
- Capture avec le masquage natif de Playwright (`page.screenshot(mask=…)`), image JPEG
  (qualité ~60, largeur ≤ 1280 px) ; les rectangles masqués sont aussi envoyés pour que le
  player les étiquette.
- **Fermé par défaut** : un script sans section `privacy` ne produit aucune image (la
  transcription reste) ; si un sélecteur déclaré pour l'écran courant est introuvable,
  l'image de cette étape n'est pas capturée et l'étape l'indique (« capture retenue :
  zone à protéger introuvable »).
- Moteurs à modèle : le modèle travaille sur l'écran comme aujourd'hui (règles d'accès aux
  données existantes) ; les images **enregistrées** pour le player sont masquées de la même
  façon ; chaque action du modèle (clic x,y, saisie, touche, défilement) devient une
  étape avec son geste.
- Les scripts de démo (`demo_portal`, `demo_bedsoft`) déclarent leurs masques ; leurs
  écrans fictifs affichent des noms inventés pour tester que le masque les recouvre.

## Contrat d'API

Poste agent (compte `ingestion`, mêmes jetons de bail que les autres appels de tâche) :

- `POST /api/agent/tasks/{task_id}/steps` (multipart) : `meta` JSON
  `{seq, at, engine, kind, label, target, pointer: {x, y} | null, box: {x, y, w, h} |
  null, outcome: "ok" | "fail" | "info", duration_ms, viewport: {w, h}, masks: [{x, y, w,
  h, reason}], transmitted: {count, fields, applied, duplicates, rejected} | null}` +
  `frame` (image/jpeg, ≤ 512 Ko, facultative). `kind` ∈ `login`, `navigate`, `click`,
  `fill`, `select`, `read`, `wait`, `scroll`, `key`, `verify`, `model_action`, `info`,
  `error`. Refus si le bail n'est pas tenu, si la tâche est finie, si l'image n'est pas un
  JPEG (octets magiques), si `label` contient une valeur interdite détectable (motif NIR,
  date de naissance) — défense en profondeur.

Interface (admin ou coordination dans son périmètre ; direction 403 ; autre groupe 404) :

- `GET /api/agent/tasks/{task_id}/replay?after_seq=N` →
  `{task: {id, kind, status, engine_used, created_at, finished_at, connection_id,
  connection_name, site_name}, live: bool, retention_until, steps: [{id, seq, at, engine,
  kind, label, target, pointer, box, outcome, duration_ms, viewport, masks, transmitted,
  has_frame}]}` ; `after_seq` sert au direct (interrogation chaque seconde tant que
  `live`).
- `GET /api/agent/steps/{step_id}/frame` → `image/jpeg` (`Cache-Control: no-store`,
  `X-Content-Type-Options: nosniff`), 404 après purge.
- `ConnectionOut` (existant) gagne `running_task_id` (tâche en cours ou null) ; chaque
  passage de `GET /connections/{id}/runs` gagne `has_replay` et `steps_count`.
- Journal d'audit : `agent.replay.view` (une entrée par utilisateur et par tâche et par
  heure au plus).

Stockage : table `agent_task_steps` (migration 0005 ; `group_id`, `task_id`, champs
ci-dessus, `frame` binaire nullable, `created_at`), index (`task_id`, `seq`) ; purge des
étapes plus vieilles que la conservation au démarrage de l'API et au signal des postes
(au plus une fois par heure). Aucune donnée identifiante n'y entre.

## Interface

- Carte de connexion : bouton **Regarder en direct** quand `running_task_id` existe
  (pastille rouge « En direct ») ; dans « Passages », bouton **Revoir** quand
  `has_replay`.
- Player : page `/agents/passages/:taskId` (anciennement `/computer-use/…`, redirigée) (plein écran possible), écran à gauche,
  transcription à droite (dessous en mobile), barre de contrôle sous l'écran, en-tête
  avec connexion, site, tâche, moteur, résultat, date et « conservé jusqu'au … ».
- Microcopies françaises, claires ; jetons de design existants ; accessible ; pas de
  défilement horizontal à 390 px.

## Critères de réussite

1. Pendant une relève de la démo, « Regarder en direct » montre les images au fil de
   l'eau (retard ≤ 2 s) avec la transcription.
2. Après la tâche, « Revoir » rejoue toutes les étapes avec les contrôles du player.
3. Sur les écrans fictifs, les noms inventés sont recouverts dans toutes les images
   (test par pixels : la zone du nom est l'aplat de masquage) ; aucun mot de passe,
   nom ou date de naissance dans la transcription ni en base.
4. Script sans `privacy` : transcription sans image. Sélecteur introuvable : image
   retenue.
5. Droits : admin et coordination de son site ; direction 403 ; autre groupe 404 ;
   visionnage journalisé. Purge après 7 jours.
6. Tous les contrôles verts ; démo vérifiée.

## Implémentation (côté API et poste agent)

Décisions prises en construisant le contrat (branche `feat/agent-player-backend`) :

- **Schéma** : migration `0005`, table `agent_task_steps` (`pointer`, `box`, `viewport`,
  `masks`, `transmitted` en JSON texte ; `frame` binaire nullable), index unique
  (`task_id`, `seq`), index sur `created_at` pour la purge.
- **Envoi d'une étape** : `meta` porte aussi `agent_id` et `lease_token` (mêmes jetons que
  `renew` / `attempts`) ; le bail est vérifié sans les contrôles de travail (pause, décision
  à jour) pour que les dernières étapes d'une tâche qu'on arrête arrivent encore ; tâche
  finie ou bail perdu : 409. `engine` doit être un moteur connu. Réponses : 201 (créée),
  200 (même `seq` renvoyé : idempotent), 411 (sans `Content-Length`), 413 (image > 512 Ko,
  ou corps > ~530 Ko refusé avant lecture), 415 (type ou octets magiques non JPEG), 422
  (`meta` stricte : champ inconnu, énumérations, longueurs, coordonnées bornées à ±20 000,
  date avec fuseau ; libellé ou cible ressemblant à un NIR, à 13 chiffres ou plus, ou à
  une **date complète** quelle qu'elle soit — une date de naissance ne se distingue pas
  d'une autre ; la valeur refusée n'est jamais renvoyée). Au plus 2 000 étapes par tâche.
- **`seq`** : croissant dans une tâche ; chaque tentative (réservation) commence à
  `(tentative − 1) × 100 000 + 1`, pour qu'une tâche reprise garde une transcription
  ordonnée sans collision. Les `seq` ne sont donc pas contigus d'une tentative à l'autre.
- **Replay** : 500 étapes au plus après `after_seq` (défaut 0) ; `live` = tâche en cours ;
  `retention_until` = création de la première étape + `ADM_AGENT_REPLAY_DAYS` (création de
  la tâche s'il n'y a pas d'étape). Coordonnées (`pointer`, `box`, `masks`) en pixels CSS du
  `viewport` de l'étape ; l'image est capturée à l'échelle CSS, donc ses pixels sont ceux du
  `viewport` (1280 × 800 sur les postes actuels).
- **Droits** : site d'une tâche = site de sa connexion. Autre groupe ou autre site
  (cadre limité) : 404 ; connexion « tout le groupe » ou tâche historique sans connexion
  vue par un cadre limité : 403 (même règle que les connexions visibles non pilotables) ;
  `direction` et `ingestion` : 403. L'image est soumise aux mêmes droits et au même audit
  `agent.replay.view` (une entrée par utilisateur, tâche et heure, vérifiée sous le verrou du
  groupe). `has_replay` vaut faux si ce lecteur ne peut pas regarder la tâche ; `steps_count`
  est donné à tous les lecteurs des passages. `running_task_id` : la tâche en cours la plus
  récente de la connexion.
- **Conservation** : `ADM_AGENT_REPLAY_DAYS` de 1 à 90 (configuration refusée sinon) ;
  purge au démarrage de l'API (tous groupes) et au signal d'un poste (son groupe, au plus une
  fois par heure et par processus d'API).
- **Poste** : `replay.py` (enregistreur et envoi). Masquage natif de Playwright, aplat
  `#4B5563` (le player dessine les hachures et l'étiquette par-dessus avec les rectangles
  reçus). **Écart** : un écran plus large que 1280 px n'est pas réduit, l'image est retenue
  (« capture retenue : écran plus large que 1280 px ») ; les postes capturent en 1280 × 800,
  sans Pillow ni redimensionnement. Image retenue aussi si la page change pendant la capture
  ou si le JPEG dépasse 512 Ko. Zone déclarée avec `screen` et introuvable : image retenue
  (`optional: true` pour l'éviter) ; zone sans `screen` : masquée là où elle paraît, sans
  exigence.
- **Libellés** : texte fixe, jamais interpolé (`label:` facultatif par étape de script,
  sinon un libellé par type d'étape ; `list.label` / `list.items`). Une saisie de modèle est
  décrite par sa longueur, une touche par son nom seulement si elle est dans la liste
  autorisée. Étapes de connexion : `kind = login`. Début et fin de passage : `info` /
  `error`. Chaque fiche lue : `read` avec `transmitted = {count: 1, fields}` ; la liste :
  `read` avec le total ; après l'envoi à l'API : `info` (ou `ok` / `fail`) avec
  `applied` / `duplicates` / `rejected` (demandes : nouvelles / déjà connues / refusées).
- **Démo** : `demo_portal` masque `#patient` sur `/dossiers/*` ; `demo_bedsoft` masque la
  colonne `td.patient` (classe ajoutée au logiciel fictif) sur `/mouvements`, et `#patient`,
  `#naissance`, `#ipp`, `#venue` sur `/mouvements/*` (IPP et venue en clair : HospitalOS ne
  les garde que pseudonymisés, ils ne doivent pas l'être en image).
- **Tests** : `services/admissions_smr/tests/test_agent_replay.py` (droits, bail, tailles et
  types, libellés refusés, purge, pagination, audit, en-têtes) ;
  `services/admissions_agent/tests/test_player.py` (Chromium réel : chaque zone de nom, date
  de naissance, identifiant et mot de passe est l'aplat de masquage dans toutes les images,
  décodées avec Pillow, outil de test seulement ; aucune valeur à l'écran ni mot de passe
  dans les étapes stockées ; sans `privacy`, pas d'image ; zone introuvable, image retenue ;
  gestes d'un moteur Claude simulé ; file d'envoi non bloquante).

## Vérification de la démo (3 novembre 2026)

Démo réelle sans Docker (API, `demo_bedsoft` sur 8120, agent `agent-mco` avec ses quatre
variables, Vite), compte `bedmanager@ch-demo.hospitalos.fr`, connexion « Gestion des lits
(démonstration) » :

- « Relever maintenant » puis « Regarder en direct » : images au fil de l'eau ; retard
  mesuré dans le navigateur entre le début d'une étape et son arrivée : 1,3 s au plus
  (0,9 s au plus après la fin de l'étape, médiane 0,5 s).
- « Revoir » après la tâche : 24 étapes, contrôles du player, clavier.
- 104 images de 8 passages relues au pixel : 0 zone déclarée non couverte ; chaque image
  de la liste a ses 7 cellules Patient masquées ; aucun nom, date de naissance, IPP, n° de
  venue ni mot de passe dans les étapes stockées ni dans les journaux de l'API, de l'agent
  et du logiciel fictif.
- Droits sur `GET /replay` : bedmanager, cadre et admin du CH 200 ; direction 403 (et le
  web affiche « Player réservé » sans appeler l'API) ; comptes de l'autre groupe 404.
- 390 px : pas de défilement horizontal (player et écran Agents, alors « Computer use »).

Captures (données fictives) : `docs/agent/captures/`.
