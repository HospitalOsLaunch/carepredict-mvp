# Cockpit HospitalOS — libérer → attribuer

Interface du MVP hybride (`src/hospitalos/hybrid`). Un seul parcours couplé :
le **cadre de santé** voit ce qui bloque chaque sortie, le **gestionnaire de lits**
voit qui attend quel lit, et les deux lisent la même proposition simulée.

Prototype local en **mode observation** : l'interface n'émet aucune commande, ne
réserve rien et n'expose aucun bouton d'exécution. L'avis « je l'aurais fait / je
ne l'aurais pas fait » est conservé sur l'appareil, pas envoyé.

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

```bash
npm run typecheck && npm test   # 61 tests : vocabulaire, dérivations, rendu
npm run build                   # dist/ pour l'API locale
npm run build:demo              # dist-demo/index.html autonome (aperçu partageable)
npm run fixtures                # régénère src/fixtures depuis le planificateur
```

## Ce que montre chaque écran

**Unité.** Une phrase de situation, puis la **proposition** (point focal) : l'action,
les faits qui la rendent lisible, l'effet simulé contre « sans action » sur les mêmes
scénarios, l'échéance. En dessous, les **sorties à libérer** sous forme de chaîne
(avis médical → documents → accompagnant → aval → transport) et, pour chaque lit, qui
pourrait le prendre. À droite, les **patients à placer** et le **tableau des lits**.

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
2. `POST /hybrid/shadow/{episode_id}/opinion` : persister l'avis du cadre ou du
   gestionnaire (verdict, motif codé, horodatage serveur, acteur authentifié). C'est la
   donnée qui mesure la pertinence en pilote silencieux.
3. Exposer le TTL de fraîcheur de la politique live dans `LiveSnapshot` (le cockpit
   suppose 5 min pour l'indice visuel « vieillissant »).
4. Authentification opérateur et périmètre par unité avant tout usage hors poste local.
