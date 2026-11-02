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
- Player : page `/computer-use/passages/:taskId` (plein écran possible), écran à gauche,
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
