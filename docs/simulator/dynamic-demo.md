> Laboratoire historique. Le lancement sans `--lab` ouvre désormais le
> [produit connecté aux hôpitaux virtuels](virtual-hospitals.md).

# Première boucle de démonstration connectée

25 octobre 2026. Statut : branche intégrée, tranche locale sur scénario fictif, non qualifiée.

Un patient attend un lit avec oxygène. Le vrai planificateur hybride propose de
prioriser le nettoyage du lit G02. Le cockpit transmet une décision à une
passerelle réservée au simulateur ; une tâche de coordination précède son effet.
Après nettoyage, réservation et transfert, l'installation du patient apparaît
dans les observations retardées du cockpit.

Cette tranche met en œuvre le raccordement décrit dans la
[spécification documentaire v0.3](spec-v0.3.md), désormais dans la même branche.
Elle ne constitue ni le moteur v0.3 complet ni la clôture de M1–M4. Le cockpit
repose sur `claude/cockpit-web`, dont le socle hybride correspond à la PR #22.

## Lancer avec une commande

Prérequis : **Python 3.11+ et Node.js 22+ avec npm**. Depuis la racine du dépôt :

```bash
python3 demo.py --lab
```

Pour récupérer ou mettre à jour cette branche depuis un clone initialement limité
à `claude/cockpit-web` avec `--single-branch`, arrêter les anciens serveurs puis :

```bash
git remote set-branches --add origin codex/integrated-demo
git fetch origin
git switch codex/integrated-demo
git pull --ff-only
python3 demo.py --lab
```

Le premier lancement crée `.venv-demo`, installe les dépendances et la pile numérique épinglées
dans `requirements-demo.txt` et lance `npm ci` avec `web/package-lock.json`.
Il nécessite un accès aux registres Python/npm. Les lancements suivants réutilisent
ces installations tant que les fichiers de dépendances n'ont pas changé.
Les dépendances Python transitives restent résolues par pip ; ce fichier n'est pas
un verrou exhaustif de toutes les plateformes.

Le lanceur attend que le simulateur réponde à travers le proxy du cockpit, puis
ouvre **http://127.0.0.1:5173/?source=simulator**. **Ctrl+C arrête les deux services.**
Il n’arrête jamais un serveur déjà présent : il choisit un port voisin libre
ou échoue si un port explicitement demandé est occupé. Une défaillance d'un des services arrête l'autre.

Aucune base hospitalière, aucun Docker, poids de modèle, GPU, fichier `.env` ou
connexion à un SI n'est nécessaire. L'environnement `.venv` du dépôt n'est pas utilisé.
`make demo` est un alias ; l'ancien parcours Docker/entraînement est `make demo-legacy`.

Options utiles :

```bash
python3 demo.py --lab --no-browser                       # afficher le lien sans ouvrir de navigateur
python3 demo.py --lab --port 5180 --api-port 8010         # autres ports locaux
python3 demo.py --lab --setup-only                       # préparer les dépendances seulement
python3 demo.py --lab --no-install                       # exiger une installation déjà préparée
python3 demo.py --lab --check                            # vérifier HTTP, planificateur et neutralité A0/A1
```

Le script fonctionne aussi depuis un autre dossier en utilisant son chemin absolu.
Python absent ou trop ancien : utiliser l'exécutable Python 3.11+ installé sur la machine.
Node/npm absent ou trop ancien : installer Node.js 22+ puis relancer la même commande.
Installation interrompue : relancer ; si `.venv-demo` est signalé incomplet, retirer
uniquement ce dossier dédié et relancer. Une session simulée n'est pas persistée.

Le paramètre `source=simulator` impose
une source connectée : une indisponibilité du serveur produit une erreur visible,
sans substitution par des fixtures. `npm run build:demo` reste l'aperçu statique
historique ; ce fichier autonome ne contient pas de moteur Python.

Le panneau **Sans / avec HospitalOS** lance une comparaison depuis le début du
scénario, sans reprendre les décisions ni modifier la séance interactive.
Choisir une graine, une durée et la réponse aux recommandations, puis **Comparer**.
Les résultats mesurés après clôture sont exportables en JSON, avec les journaux
et les empreintes du code. Le [protocole de comparaison](comparison.md) décrit
la politique A0/A1, les coûts, les limites et le rejeu en ligne de commande.

Pour travailler dans deux terminaux, après `python3 demo.py --lab --setup-only` :

```bash
# Terminal 1, depuis la racine (macOS/Linux)
PYTHONPATH=src:. .venv-demo/bin/python web/dev/serve_simulator_api.py --seed 7
# Terminal 2, depuis la racine
cd web
npm run dev
```

Dans ce mode manuel, ouvrir http://localhost:5173/?source=simulator. Le proxy vise
le port 8000 par défaut. `HOSPITALOS_DEMO_API_PORT` permet de changer son port local.

La session démarre en pause. Cliquer « Évaluer le scénario », puis « Appliquer
dans le scénario ». Avancer le temps avec +1/+5 minutes ou « Lire ×60 » ; la pause
et les expirations reposent sur la même horloge serveur. La priorité change
l'ordre des tâches en attente, pas leur durée. Observer ensuite G02 et P-G01.
« Terminer et mesurer » ferme l'épisode et rend accessible son évaluation.
« Recommencer » crée une nouvelle identité de séance avec les mêmes aléas.

## Raccordement et séparation des accès

| Composant | Chemin | Responsabilité |
| --- | --- | --- |
| Monde physique SimPy | `src/hospitalos/simulator/engine.py` | Lits, patients, événements, ressources, tâches et vérité privée |
| Projection déclarée | `src/hospitalos/simulator/feed.py` | Exports JSON complets d'observations, puis `SourceAdapter` et `LiveStore` existants |
| Session et commandes | `src/hospitalos/simulator/session.py` | Horloge, identités, revalidation, déduplication et passerelle vers le seul monde simulé |
| API locale distincte | `services/api/simulator_app.py` | Routes de démonstration et lecture hybride ; aucune destination hospitalière configurable |
| Cockpit connecté | `web/src/data/useSimulation.ts`, `web/src/ui/Simulation.tsx` | Affichage des observations, commandes explicitement simulées et erreurs de connexion |
| Notateur | `src/hospitalos/simulator/evaluation.py` | Reconstruction de l'intégrale d'attente depuis le journal après clôture |

Le moteur de vérité n'importe pas le planificateur. Les professionnels de
référence choisissent à partir des observations livrées, puis vérifient les
préconditions physiques. La vérité, les durées tirées, la graine et les prochains
événements ne sont pas transmis aux routes de lecture ou de planification.
L'évaluation n'est visible qu'après clôture ; aucun nouvel arbitrage ne peut alors
être appliqué à cet épisode.

La projection vers HYBRID_MVP_2 est volontairement bornée : un lit en nettoyage
reste déclaré sale et la disponibilité de l'équipe passe à zéro lors de son
observation. Ce contrat ne représente pas la tâche de nettoyage en cours ni son
temps restant. Le planificateur peut donc s'abstenir ou ne proposer aucun changement
pendant cette phase ; il ne reçoit pas une durée de fin cachée.

## Contrat HTTP

| Route | Effet |
| --- | --- |
| `GET /demo/session` | Horloge courante, instantané déclaré, proposition encore valide, reçus d'action et évaluation éventuelle |
| `POST /demo/evaluate` | Épisode du planificateur réel sous hypothèses déclarées ; aucune exécution |
| `POST /demo/control` | Avancer, lecture, pause, couper/rétablir la source, terminer ou recommencer |
| `POST /demo/decision` | Accepter/refuser la proposition enregistrée dans la session, avec coût et contrôle physique différés |
| `GET /hybrid/live` | Même instantané du `LiveStore` en mode shadow |
| `POST /hybrid/shadow` | Évaluation seule, toujours zéro commande émise par cette route |

Les commandes de contrôle et de décision portent `run_id`, `revision` et `request_id`. La décision porte
aussi `plan_id`, l'empreinte sémantique de l'instantané et un booléen `accept`.
Aucun champ d'action libre n'est accepté. Un rejet de version, de validité ou de
précondition impose une réévaluation ; il n'est pas réessayé automatiquement.

Un même identifiant et un même contenu sont idempotents dans la session. Réutiliser
un identifiant avec un autre contenu est refusé. Une seule décision consomme une
proposition. Les mutations concurrentes sont sérialisées. Après un redémarrage ou
un reset, les anciens identifiants de séance sont refusés, y compris le rejeu du
reset : ils ne peuvent pas agir sur le nouveau monde.

Une acceptation n'est pas une preuve d'exécution. La passerelle conserve
`accepted`/`refusal_recorded`, puis `executed`/`refused`/`failed`. `executed`
signifie que la priorité ou réservation est appliquée ; la fin de nettoyage et
l'installation restent des événements ultérieurs. Les validations historiques
du journal local du cockpit restent réservées au mode observation. Le mode
simulé possède ses propres contrôles et son journal serveur.

## Hypothèses de cette tranche

Toutes les valeurs sont des hypothèses d'ingénierie du scénario `demo-world-1`.

- Trois lits et trois places armées ; G02 possède l'oxygène. Un patient attend
  dès le début, un patient est déjà hospitalisé et un autre arrive à dix minutes.
- Une équipe de nettoyage. Première prise en charge à deux minutes, puis examen
  de la file chaque minute. Durées de 15, 20 ou 25 minutes, tirées par graine,
  mécanisme et lit. La priorité ne préempte pas un nettoyage commencé.
- Une sortie préautorisée à quarante minutes, suivie du besoin de nettoyage.
  Aucune décision médicale nouvelle ni amélioration clinique due à une action.
- Un coordinateur : 30 secondes pour lire/traiter une décision, y compris refus,
  partagées avec le lancement des affectations. Installation en 60 secondes après
  réservation ; vérification physique à la réservation et à l'installation.
- Observation directe synthétique de l'unité chaque minute ; livraison 30 secondes
  plus tard. Ce recensement exogène n'est pas un modèle calibré de travail soignant.
  En panne, les nouvelles livraisons sont supprimées ; le dernier état vieillit.
- Horloge UTC ancrée au 25 octobre 2026, affichage Europe/Paris. Événements à la
  borne d'un pas inclus, ordre SimPy stable. Durée maximale : trois heures.
- L'avancement automatique est calculé à partir de l'horloge monotone serveur
  lors des requêtes ; l'interface interroge chaque seconde. Il n'y a pas de worker
  autonome : après une interruption des requêtes, le calcul rattrape le temps
  écoulé au prochain accès, jusqu'à la borne de trois heures.

Les hypothèses du planificateur sont déclarées séparément. Elles ne sont pas les
tirages réalisés du monde physique. La comparaison de valeurs prédites et
réalisées ne prouve aucune efficacité. Le résultat final concerne seulement cet
épisode et inclut les patients qui attendent encore à la clôture.

## Vérifications et limites

```bash
python3 demo.py --lab --setup-only
python3 demo.py --lab --no-install --check
.venv-demo/bin/python -m pip install httpx 'pytest>=8.2,<9' 'ruff>=0.4,<1' 'mypy>=1.10,<2'
PYTHONPATH=src:. .venv-demo/bin/python -m pytest -q tests/hybrid tests/simulator tests/demo
.venv-demo/bin/python -m ruff check demo.py tests/demo src/hospitalos/simulator services/api/simulator_app.py web/dev/serve_simulator_api.py tests/simulator
.venv-demo/bin/python -m ruff format --check demo.py tests/demo src/hospitalos/simulator services/api/simulator_app.py web/dev/serve_simulator_api.py tests/simulator
PYTHONPATH=src:. .venv-demo/bin/python -m mypy --strict demo.py tests/demo src/hospitalos/simulator services/api/simulator_app.py web/dev/serve_simulator_api.py tests/simulator
cd web
npm run typecheck
npm test
npm run build
```

Les cas couvrent la boucle avec le vrai planificateur, le retard de déclaration,
la réservation/installation, le refus coûteux, les échecs physiques après
acceptation, l'expiration, la concurrence, les doublons, les anciennes séances,
la panne/reprise, l'horloge accélérée, le rejeu et l'évaluation d'attentes inachevées.
Le notateur rejette les journaux falsifiés sur ses invariants vérifiés. Les tests
du cockpit couvrent le mode connecté et l'absence de repli silencieux.

Cette application est mono-processus, en mémoire et sur loopback. Les sessions
ne sont pas persistées après arrêt ; le seed permet de rejouer le scénario.
Ne pas lancer plusieurs workers partageant une prétendue session. Les origines
web externes sont rejetées ; cela ne constitue pas une authentification ni une
architecture de déploiement distant.

Restent hors de cette tranche : modèle clinique complet, minutes par rôle du
chapitre 6, PAM/FHIR/écrans du faux SI, aval territorial, campagne de 1 000 jours,
apprentissage et qualifications C1–C6/I1/U1. Aucun statut SIM_GO_* ni bénéfice
hospitalier n'est déclaré acquis.
