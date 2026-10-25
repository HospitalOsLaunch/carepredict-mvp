# Cockpit HospitalOS — libérer → attribuer

Interface du MVP hybride (`src/hospitalos/hybrid`). Un seul parcours couplé :
le **cadre de santé** voit ce qui bloque chaque sortie, le **gestionnaire de lits**
voit qui attend quel lit, et les deux lisent la même proposition simulée.

Conçu pour l'usage en tension : bande de tension lisible en un regard, une seule action
suivante, flux Libérer → Lits → Attribuer, changement d'unité sans ouvrir chaque unité, et
tout au clavier (`?` affiche les raccourcis).

Par défaut, prototype local en **mode observation** : l'interface n'émet aucune commande, ne
réserve rien et n'expose aucun bouton d'exécution. Valider une proposition signifie « je
m'en occupe » : la personne agit dans ses outils habituels, HospitalOS garde la trace (validée,
faite, refusée avec motif, sans réponse, remplacée) dans le journal des décisions, conservé sur
le poste dans ce prototype. Le mode explicite `?source=simulator` ajoute une
boucle de décisions dont les effets sont limités à un hôpital fictif (voir ci-dessous).

## Lancer

### Démonstration dynamique connectée

Depuis la racine, **`python3 demo.py`** prépare les dépendances et lance le backend
et ce cockpit dans un seul terminal. Le navigateur s'ouvre avec **`?source=simulator`**.
Ctrl+C arrête les deux services. Prérequis : Python 3.11+ et Node.js 22+ avec npm.

La [première boucle simulée](../docs/simulator/dynamic-demo.md) alimente le même
backend avec une unité gériatrique qui évolue. Les contrôles explicites de ce mode
appliquent les décisions uniquement dans le scénario et partagent son horloge.
Une panne du serveur est affichée ; aucun repli sur les données précalculées.

### Démonstration d'observation historique

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

Vite relaie `/api/*` vers `http://127.0.0.1:8000` par défaut ; le lanceur intégré
peut choisir un autre port local avec `--api-port`. En observation historique,
le cockpit détecte seul la source :

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
npm run typecheck && npm test   # régressions du cockpit et scénario connecté
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
  En mode simulateur, elle utilise directement l'horloge du scénario, y compris en pause.

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
