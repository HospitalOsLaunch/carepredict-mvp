# Produit connecté à des hôpitaux virtuels

Le parcours par défaut est le cockpit métier : choisir X1, X2 ou X3, lire la
situation de l’unité, examiner une proposition, la valider ou la refuser avec un
motif, puis suivre les observations et le journal. Les hôpitaux évoluent en
arrière-plan sans onglet ouvert. Il n’y a ni sélecteur de scénario, ni commande
d’horloge, ni campagne de comparaison dans ce parcours.

## Lancement et reprise

Python 3.11+, Node.js 22+ et npm, depuis la racine :

```bash
python3 demo.py
```

Le lanceur prépare ses dépendances, vérifie le backend à travers le proxy et
ouvre le cockpit. Les ports par défaut sont 5173/8000 ; un port voisin libre est
choisi si nécessaire. Un port explicitement demandé reste strict : aucun ancien
processus n’est arrêté. Ctrl+C arrête les deux services et conserve l’état.

```bash
python3 demo.py --check
python3 demo.py --port 5180 --api-port 8010
python3 demo.py --state-dir /chemin/autre-session --seed 12
python3 demo.py --lab  # ancien laboratoire, explicitement séparé
```

Le dossier `.hospitalos-virtual` contient les bases SQLite par établissement et
un verrou d’exécution (macOS/Linux). Un seul backend peut utiliser ce dossier.
Si un ancien backend tourne, l’arrêter dans son terminal avant de relancer.
Les identités, intentions de décision, motifs et éléments de preuve sont
persistés. La reprise rejoue les primitives et intentions jusqu’au dernier
checkpoint (toutes les cinq secondes réelles et à l’arrêt propre). Les décisions
sont persistées avant leur transmission ; une panne ne les efface pas. Le temps
écoulé depuis le dernier checkpoint sans décision peut être rejoué après une panne.
Un changement de graine/configuration exige un autre dossier, sans effacement
implicite. Une modification incompatible de mécanique doit incrémenter la
version d’identité du moteur avant de réutiliser des états persistés.

Le temps avance à ×12 par défaut (`--clock-rate`, développeur). Il s’arrête quand
le backend est arrêté ; une veille de plus de cinq minutes est traitée comme
une pause. Ce n’est pas une horloge hospitalière réelle. Le badge et le pied de
page rappellent que tous les patients et établissements sont fictifs.

## Quatre étapes intégrées

| Étape | Livraison | Accès |
| --- | --- | --- |
| Hypothèses configurables | Contrat fermé `HospitalConfig`, capacités, lits oxygène, arrivées, séjours, sorties et délais SI | Python/JSON développeur |
| Trois régimes | X1 nominal, X2 afflux, X3 nettoyage contraint | Mondes autonomes derrière les noms d’établissements |
| Campagnes appariées | A0/A1 séparés, graines fixées avant exécution, primitives indexées | CLI hors produit |
| Mesures et exports | Journaux complets, résultats par réplication, dispersion et dégradations, reprise vérifiée | JSON et Markdown hors produit |

Chaque hôpital a une unité gériatrique de 14 lits dotés, dont quatre avec oxygène,
une équipe de nettoyage, dix patients initialement installés et deux en attente.
Les identifiants patient/lit sont locaux : seul le couple établissement/identifiant
est global. Les hôpitaux ne partagent ni états, ni décisions, ni ressources.

| Hypothèse | X1 | X2 | X3 |
| --- | --- | --- | --- |
| Intervalle d’arrivée | 20/30/40 min | 8/12/15 min pendant les deux premières heures de chaque journée virtuelle, puis 20/30/40 | 20/30/40 min |
| Nettoyage | 15/20/25 min | 15/20/25 min | 30/45/60 min |
| Export SI / délai de livraison | 60 s / 30 s | 60 s / 45 s | 60 s / 60 s |

Les supports sont équiprobables, fictifs et non calibrés. Les nouveaux séjours
avant autorisation de sortie durent 4/6/8 h ; le départ suit cette autorisation
avec un délai de dix minutes. Les autorisations initiales sont préprogrammées.
Aucune recommandation ne modifie une décision clinique. Les admissions normales
utilisent les observations livrées, la compatibilité et une priorité d’attente
par tranches de 60 minutes. Réservation atomique, puis installation en 60 secondes.
Le nettoyage est non préemptif ; une priorité modifie l’ordre des tâches, jamais
leur durée. Le planificateur conserve ses propres hypothèses 15/20/25 minutes,
y compris pour X3 : il ne lit pas les tirages réalisés du monde.

Pour des configurations développeur : fournir une liste JSON de `HospitalConfig`
à `web/dev/serve_virtual_api.py --config fichier.json --state-dir autre-dossier`,
avec `PYTHONPATH=src:.` et le Python de `.venv-demo`. Ce réglage n’est pas exposé
au cadre de santé. Le lanceur normal conserve les trois établissements de référence.

## Frontières techniques et métier

`VirtualEngine → export déclaré retardé → SourceAdapter → LiveStore →
planificateur hybride → API produit → cockpit`. Chaque export complet reconstruit
une projection bornée du LiveStore. Cette projection courante ne prétend pas être
un entrepôt bitemporel historique ; les preuves de chaque décision sont conservées
séparément dans SQLite. L’évaluation scientifique reconstruit les métriques depuis
le journal de vérité, inaccessible aux routes produit.

Routes : `GET /product/hospitals`, `GET /product/hospitals/{id}/unit`,
`POST /product/hospitals/{id}/decisions`. Les routes `/demo/*` ne sont pas montées.
Le serveur vérifie établissement, session, révision, proposition et empreinte de
l’observation, puis les préconditions physiques à l’exécution. Une répétition du
même identifiant/requête est idempotente ; un contenu différent est refusé.
Une réponse tardive d’un autre établissement ne peut remplacer l’écran courant.
Une panne du flux affiche une erreur et bloque la validation sans repli sur fixtures.

La coordination prend 30 secondes par décision, y compris un refus. L’accusé
« prise en charge » confirme la commande, pas une installation ou un nettoyage
terminé. Ces effets reviennent par les observations retardées. Le journal montre
les 50 dernières décisions de l’établissement ; l’historique durable est conservé.
Le signataire « Équipe de garde » est une identité de démonstration, pas une identité
authentifiée. Ce produit local n’a pas de contrôle d’accès multi-utilisateur ni de
connecteur hospitalier réel.

Le monde n’a pas de fin à trois heures. Les séjours, arrivées, sorties et nettoyages
se répètent. Une limite explicite de 120 patients actifs provoque une indisponibilité
visible, sans perte silencieuse des arrivées. Les journaux de vérité/primitives et
les patients historiques restent en mémoire : cette version vise les séances de
démonstration, pas un service sans limite de rétention. Le rejeu au démarrage croît
avec la durée conservée. Les ressources sont agrégées ; pas encore de personnel
individuel, transports/SMR détaillés, corrections SI historiques ou calibration
clinique. La spécification v0.3 reste la cible, ses jalons ne sont pas déclarés clos.

## Campagnes indépendantes du produit

```bash
PYTHONPATH=src:. .venv-demo/bin/python -m hospitalos.virtual.campaign \
  --output virtual-campaigns/reference
# Contrôle de neutralité
PYTHONPATH=src:. .venv-demo/bin/python -m hospitalos.virtual.campaign \
  --output virtual-campaigns/neutralite --policy disabled --hours 1 --seeds 7
```

La référence fixe dix graines (0 à 9), trois établissements et six heures, soit
30 paires / 60 épisodes. A0 utilise uniquement le fonctionnement ordinaire ; A1
examine les propositions toutes les cinq minutes et accepte celles applicables.
`--policy refuse` teste le refus avec coût de coordination ; `disabled` exige
l’identité complète des deux trajectoires. Les commandes n’agissent jamais sur
les bases utilisées par le cockpit. `--config` accepte les mêmes hypothèses JSON.

Les primitives sont indexées par version, établissement, graine, mécanisme, entité
et occurrence (notamment les nettoyages répétés). Les clés communes aux deux bras
ont les mêmes valeurs ; les événements supplémentaires peuvent introduire de
nouvelles clés. Chaque paire redémarre du même état initial et du même calendrier
exogène. Les scénarios prédictifs du planificateur ne sont pas ces réalisations.

`manifest.json` fige code, dépendances suivies, hypothèses, graines et cadence.
Chaque paire exporte son journal, les primitives, propositions, commandes et
mesures. `progress.json` indique avancement ou échec. Relancer la même commande
reprend les paires terminées après vérification du manifeste et de leur empreinte ;
un code/configuration différent exige un nouveau dossier. Une seule campagne
par dossier à la fois. Les fichiers JSON sont écrits par remplacement atomique.

`report.json` et `report.md` montrent les résultats par établissement et les
réplications : moyenne, médiane, écart-type, minimum, maximum, améliorations,
égalités et dégradations. L’écart signé A0 − A1 mesure les minutes-patients d’attente,
y compris les attentes non terminées à l’horizon. Un résultat négatif reste visible.
La coordination est rapportée séparément (30 s demandées par décision), sans
conversion arbitraire en gain patient. Aucun intervalle de confiance clinique,
aucune preuve de bénéfice réel : ce banc évalue des mécanismes sur hypothèses.

La [campagne de référence exécutée](evidence/virtual-reference-2026-10-25/README.md)
conserve les 30 paires et leurs journaux, avec les résultats agrégés et individuels.
