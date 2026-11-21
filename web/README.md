# Cockpit HospitalOS — libérer → attribuer

<a id="simuler-une-affectation"></a>

## Simuler le plan de midi

Depuis la racine du dépôt, exécuter `make demo-world-model` puis ouvrir
[le cockpit de simulation](http://127.0.0.1:5173/#/simulation). Le lanceur vérifie Python 3.11+,
Node.js 22+, npm et un compilateur C++17. Il prépare les dépendances et sert les API sur le même port.
`Ctrl+C` ferme les services. Autre port possible avec `make demo-world-model DEMO_ARGS='--port 5180'`.

1. Choisir un établissement et lire le planning de 8 h. À midi, ouvrir **Plan composé** et choisir le critère de classement : attente cumulée d’un lit, file de transfert à 16 h ou minutes de soins IDE et AS non couvertes.
2. Comparer les propositions au planning de référence ou **composer son plan**. Chaque ligne identifie un dossier ou une ressource, une quantité, une unité de soins et un créneau. Aux Rives, **Essayer le plan à 8 actions** sélectionne S1 et S2 en sortie, A1 à A3 en entrée, un remplacement IDE, une réaffectation AS et un renfort AS.
3. **Évaluer ma composition** calcule ses effets conjoints. **Comparer les sous-ensembles** cherche les meilleures combinaisons dans la sélection. La référence conserve les créneaux ordinaires des dossiers connus. Un plan peut n’avancer qu’une partie de ces dossiers. Consulter les effets par unité et les dossiers retardés avant de choisir.
4. **Valider le plan en simulation**, puis avancer à 16 h. Le journal conserve le choix complet, le critère, les coûts et les alternatives disponibles à midi. Aux Rives, comparer prévisions et réalisations pour chaque action. Le Parc dispose d’un relevé partiel. Au Belvédère, le relevé de 16 h arrive à 18 h. Les simulations alternatives restent des estimations.
5. Recharger pour retrouver le plan confirmé. **Nouveau parcours** permet de tester une autre décision. **Action unique** donne accès à l’expérience initiale.

| Famille de ressources | Décisions possibles | Effets et contraintes simulés |
|---|---|---|
| Personnel IDE et AS | Remplacer une absence, faire venir un renfort qualifié, réaffecter une personne identifiée | Budget et disponibilités partagés, minutes non couvertes, couverture de l’unité prêteuse vérifiée chaque heure |
| Lits | Ouvrir un lit équipé, coordonner des sorties et avancer des entrées acceptées | Lits propres disponibles, admissions et sorties, file d’entrée et attente cumulée. Chaque dossier nommé requiert une place entière et ses conditions de prise en charge |
| Transport | Prioriser les transports d’une unité | Capacité utilisée, partagée entre les sorties, les transferts et les départs en SMR |
| Bionettoyage | Prioriser la remise en état dans une unité | Lits nettoyés et remis à disposition, sous la limite de l’équipe et du nombre de lits sales |
| Aval SMR | Allouer une place supplémentaire en soins médicaux et de réadaptation | Une place sur la période, avec un départ réalisable et un transport disponible |

Le modèle d’état déroule chaque composition de midi à 16 h sous les mêmes arrivées et disponibilités que la référence. Un renfort peut rendre possible un prêt de personnel qui, seul, laisserait l’unité d’origine en sous-effectif. Deux affectations d’une même personne, d’une même équipe ou d’une même place sur le même créneau sont bloquées.

Le classement automatique protège les admissions totales, les réorientations de l’établissement et les horaires des dossiers identifiés par rapport à la référence. Le cadre peut examiner un plan faisable qui comporte un compromis signalé. Le détail par unité montre notamment si une file s’allonge ailleurs. Le moteur compare tous les sous-ensembles jusqu’à **12 actions** dans le périmètre. Au-delà, le cockpit affiche que la recherche est limitée. La comparaison manuelle reste disponible. Le JEPA de l’expérience J7 couvre la référence et certaines actions unitaires de logistique. Les plans composés utilisent le modèle d’état sous contraintes.

L’[inventaire des offres](../src/hospitalos/world_model/data/noon_offers.json) et le [registre des dossiers et affectations](../src/hospitalos/world_model/data/noon_cases.json) décrivent les trois établissements synthétiques. Les dossiers d’entrée nommément présents fixent un minimum pour la file de leur unité lorsque le recensement agrégé est incomplet. Une entrée programmée et confirmée hors du recensement, comme A1 aux Rives, est comptée à midi dans chaque scénario, y compris la référence. Les coûts sont des hypothèses de démonstration. La validation humaine et le relevé se déroulent intégralement en simulation.

L’API crée ou relit la session avec `PUT|GET /world-model/sessions/{id}`. Sous cette route, `GET /plans?objective=bed_wait` présente les recommandations, `POST /plans/preview` évalue la sélection, `POST /plans/optimize` compare ses sous-ensembles, `POST /plans/confirm` enregistre le choix, et `POST /advance` avance l’horloge. Le navigateur utilise le préfixe `/api`. Les écritures sont atomiques. L’identifiant de session persiste dans le navigateur et la décision dans SQLite, sous `${XDG_STATE_HOME:-~/.local/state}/hospitalos/world-model.sqlite` ou dans le fichier désigné par `HOSPITALOS_WORLD_MODEL_DB`.

## Cockpit d’unité

Interface du MVP hybride (`src/hospitalos/hybrid`). Un seul parcours couplé :
le **cadre de santé** voit ce qui bloque chaque sortie, le **gestionnaire de lits**
voit qui attend quel lit, et les deux lisent la même proposition simulée.

Conçu pour l'usage en tension : bande de tension lisible en un regard, une seule action
suivante, flux Libérer → Lits → Attribuer, changement d'unité sans ouvrir chaque unité, et
tout au clavier (`?` affiche les raccourcis).

Prototype local en **mode observation** : l'interface n'émet aucune commande, ne
réserve rien et n'expose aucun bouton d'exécution. Valider une proposition signifie « je
m'en occupe » : la personne agit dans ses outils habituels, HospitalOS garde la trace (validée,
faite, refusée avec motif, sans réponse, remplacée) dans le journal des décisions, conservé sur
le poste dans ce prototype.

## Lancer

```bash
cd web
npm ci
npm run dev                 # http://localhost:5173
```

Sans API joignable, le cockpit bascule sur les **données de démonstration** :
sorties du vrai planificateur sur une unité fictive (`src/fixtures`, générées).

Avec l'API locale (depuis la racine du dépôt) :

```bash
# API hybride + unité fictive en mode shadow (horloge figée à 08:30)
PYTHONPATH=src:. python web/dev/serve_demo_api.py
# … ou horloge qui avance : les confirmations deviennent périmées, l'outil s'abstient
PYTHONPATH=src:. python web/dev/serve_demo_api.py --ageing
```

Vite relaie `/api/*` vers `http://127.0.0.1:8000` (`services/api/hybrid_app.py`,
inchangé). Le cockpit détecte seul la source :

| Source | Détection | Appels |
|---|---|---|
| API locale, unité en direct | `GET /hybrid/live` répond | `GET /hybrid/live`, `POST /hybrid/shadow` (chaque évaluation = un épisode) |
| API locale, scénarios fictifs | `/health` répond, pas de LiveStore | `POST /hybrid/plan` avec les requêtes de démonstration |
| Démonstration | API injoignable | aucun ; sorties précalculées |

La démonstration couvre quatre unités fictives d'un même pôle, chacune calculée par le vrai
planificateur : médecine polyvalente (proposition, plus trois situations), court séjour
gériatrique sous tension (proposition), médecine interne (rien à changer), pneumologie dont le
flux s'est interrompu (abstention). L'API locale ne sert qu'une unité à la fois ; le sélecteur
s'adapte.

```bash
npm run typecheck && npm test   # 66 tests : vocabulaire, dérivations, rendu, unités, raccourcis, cycle de décision, journal
npm run build                   # dist/ pour l'API locale
npm run build:demo              # dist-demo/index.html autonome (aperçu partageable)
npm run fixtures                # régénère src/fixtures depuis le planificateur
```

## Ce que montre chaque écran

**Unité.** La **bande de tension** (à placer, lits utilisables, sorties, données), puis
l'**action suivante** (point focal) : l'action, les faits qui la rendent lisible, l'effet
simulé contre « sans action » sur les mêmes scénarios, l'échéance, deux réponses. Puis le flux :
**Libérer** (chaîne avis médical → documents → accompagnant → aval → transport et la seule étape
qui manque), **Lits** (tableau en aimants), **Attribuer** (patients à placer par priorité).

**Proposition.** Toutes les options simulées (moyenne et pire décile, version tableau),
le déroulé apparié d'un scénario, les hypothèses déclarées et la traçabilité (plan,
empreinte d'état, graine, contrat).

**Données.** État reconstruit et contrôles en échec, âge des informations, ressources
confirmées, dernier export de la source, journal d'observation, et ce que le prototype
ne fait pas.

## Règles de conception

- **Le backend reste l'autorité.** Étapes, blocages, péremption et décision viennent de
  l'API ; l'interface ne relit les faits que pour montrer *quel maillon* manque.
- **L'abstention est un état de premier rang** : pas de proposition sur un état
  incomplet, périmé ou contradictoire, avec la liste de ce qu'il faut mettre à jour.
  Un lit exclu par le backend reste sur le tableau, hachuré, « Périmé » ou « Manquant ».
- **Inconnu ≠ zéro ≠ non requis** : trois rendus distincts (hachuré, bloqué, pointillé).
- **L'encre pâlit** : chaque information affiche son âge ; seule l'API la déclare périmée.
- **Aucune revendication** : « simulation sous hypothèses synthétiques » sur chaque
  proposition ; le protocole v2 non concluant est rappelé dans l'écran Données.
- **Identifiants pseudonymes uniquement** ; aucun nom, aucune valeur source affichée
  par la qualification.
- **Horloge** : l'interface ancre le temps sur l'instant reconstruit par le serveur
  (`state.at`) plus le temps écoulé, jamais sur l'horloge du poste. Une proposition
  live expire au TTL de l'évaluation (120 s par défaut), un plan à 15 min.

Système visuel : `DESIGN.md`.

## Suite côté API (non livré ici)

1. `GET /hybrid/shadow/latest` : retrouver la dernière évaluation après un rechargement.
2. Journal des décisions partagé, qui remplace le stockage local de `src/data/journal.ts` :
   `POST /hybrid/decisions/{plan_id}/events` (validée, faite, refusée, finalement non, note ;
   motif codé, acteur authentifié, horodatage serveur) et `GET /hybrid/decisions?unit=&since=`
   pour l'historique. C'est aussi la donnée qui mesure la pertinence en pilote silencieux, et ce
   qui permet à un collègue d'ouvrir le lien `#/journal/<id>` depuis un autre poste.
3. Exposer le TTL de fraîcheur de la politique live dans `LiveSnapshot` (le cockpit
   suppose 5 min pour l'indice visuel « vieillissant »).
4. Authentification opérateur et périmètre par unité avant tout usage hors poste local.

## Plan à 24 h (moteur d'aide à la décision)

Route `#/plan` (« Plan 24 h », touche `P`) : proposition calculée automatiquement par
`src/hospitalos/decision_support` sur une unité fictive distincte, puis mode manuel X1/X2 sur le
même moteur. Vite relaie `/api/decision/*` vers `web/decision/serve.py` (127.0.0.1:8765) ; sans ce
serveur, l'écran affiche les sorties embarquées (`src/fixtures/decision.json`, générées par
`web/dev/build_decision_fixtures.py`). Voir `docs/decision_support/README_REPRISE.md`.
