# Comparaison A0/A1 sur la démonstration dynamique

25 octobre 2026. Contrat `PAIRED_DEMO_1`. Scénario fictif de trois lits,
sans qualification hospitalière ni clôture du jalon M3.

## Utiliser le cockpit

Lancer `python3 demo.py`, ouvrir le panneau **Sans / avec HospitalOS**, puis
cliquer **Comparer**. La graine est 7, la durée trois heures et la réponse
« recommandations acceptées » par défaut. Une et deux heures sont également
disponibles. Le calcul peut durer plusieurs dizaines de secondes selon la machine.

La comparaison crée deux mondes neufs depuis l'origine du scénario. Elle ne
reprend pas les interventions ni les pannes de la séance interactive ; elle ne
modifie pas cette séance. Une séance en lecture poursuit son horloge normale.
Changer les paramètres efface le résultat affiché pour éviter une attribution
à une mauvaise configuration. Une erreur ne produit aucun résultat de remplacement.

### Dépannage du comparateur

Une séance interactive terminée ne bloque pas la comparaison : les deux épisodes
sont indépendants. En revanche, après un `git pull`, Vite peut actualiser le
cockpit alors que le processus Python continue d'exécuter l'ancien backend.
Arrêter la démo avec **Ctrl+C**, puis relancer **`python3.11 demo.py`** et recharger
la page pour disposer des deux composants à jour.

Le message d'erreur distingue maintenant : endpoint absent (HTTP 404/405),
comparaison déjà en cours (429), exception interne du moteur (500), indisponibilité
du moteur/proxy (502/503/504), provenance modifiée imposant un redémarrage,
réponse incompatible et délai client de 120 secondes dépassé. Ce délai ne tue pas
le calcul côté serveur : attendre sa fin avant de réessayer avec une heure simulée.

Si l'erreur persiste après redémarrage, conserver le statut affiché et les lignes
du terminal après `POST /demo/compare`. Pour vérifier rapidement l'endpoint,
depuis un second terminal pendant que la démo tourne (port par défaut) :

```bash
curl -i -sS --max-time 30 -X POST http://127.0.0.1:8000/demo/compare \
  -H 'Content-Type: application/json' \
  -d '{"seed":7,"horizon_minutes":1,"policy":"disabled"}'
```

## Politiques figées et informations disponibles

| Branche / mode | Comportement |
| --- | --- |
| A0, référence métier | Nettoyage par identifiant de lit, affectation FIFO compatible à partir des observations livrées ; une équipe de nettoyage, un coordinateur |
| A1, acceptation | Même fonctionnement automatique, plus une évaluation du vrai planificateur à 30 s puis toutes les 300 s ; toute recommandation applicable est acceptée |
| A1, refus | Même cadence ; toute recommandation applicable est refusée, avec son coût de lecture et de coordination |
| A1, désactivé | Aucun appel au planificateur, aucune sollicitation, aucun coût additionnel ; contrôle strict de neutralité |

L'acceptation systématique est une hypothèse expérimentale, pas un modèle
calibré d'adhésion professionnelle. Les actions prises en charge restent
`prioritize_cleaning` et `reserve_bed`. Une abstention, une absence de changement
ou une proposition non exécutable est enregistrée sans envoyer de commande.
Les décisions utilisent le canal déclaré `SourceAdapter → LiveStore` et les
mêmes contrôles de fraîcheur et d'application que la séance interactive.
Les journaux de vérité et les aléas futurs ne sont pas transmis au planificateur.

Les évaluations ont 16 scénarios de prévision, un horizon de 120 minutes,
une graine de planification 7 et les hypothèses de nettoyage 15/20/25 minutes.
La graine du monde ne devient pas celle de ses prévisions. Le calcul logiciel
ne consomme pas de temps hospitalier modélisé. Chaque sollicitation d'action
consomme 30 secondes du coordinateur, même refusée. Les ressources et contraintes
physiques restent identiques ; le nettoyage en cours n'est jamais interrompu.

## Couplage et résultat mesuré

Les deux mondes partent du même état initial et du même calendrier exogène.
Les durées de nettoyage sont tirées par clé
`demo-world-1|graine|cleaning|lit|0`, avec SHA-256, dans le même support.
Il n'existe qu'une occurrence par lit dans ce scénario borné. L'arrivée de
P-G02 à 600 s et le départ préautorisé de P-G00 à 2 400 s sont déterministes.
L'export conserve ces primitives. L'ordre et les dates des événements résultent
des politiques dans chaque monde ; les états futurs ne sont pas recopiés.

La fenêtre commence à 0 et finit à la durée choisie (1 à 180 minutes dans l'API).
Le notateur reconstruit après clôture l'intégrale du nombre de patients en attente
depuis les journaux, y compris les transferts avant installation et les attentes
inachevées. L'indicateur affiché est **W(A0) − W(A1)** en minutes-patients ; une
valeur négative signifie davantage d'attente avec A1. L'export donne aussi les
heures-patients. Aucun gain prédit par le planificateur ne remplace ce score réalisé.

Le tableau conserve installations pendant l'épisode, stocks terminaux, départs,
sollicitations et temps demandé par celles-ci. Ce temps est le nombre de
sollicitations multiplié par 30 s : il inclut le travail encore dû à la clôture
et ne mesure pas toute la charge soignante. Les résultats et journaux conservent
les commandes encore en cours à l'horizon, les refus et les échecs.

Cas déterministes de régression sur une heure, acceptation systématique :

| Graine | W(A0) | W(A1) | A0 − A1, minutes-patients |
| --- | ---: | ---: | ---: |
| 7 | 67 | 62 | +5 |
| 0 | 47 | 52 | −5 |

Ces exemples montrent que le signe peut changer ; ils ne sont pas une campagne
statistique. Changer la graine ne diversifie que les durées de nettoyage, pas
la structure, les patients ou le calendrier. Aucun intervalle d'incertitude,
test de supériorité, gain moyen ou bénéfice réel n'est revendiqué.

## Export et rejeu

**Exporter la comparaison (JSON)** télécharge exactement la réponse finale :
configuration, état initial, primitives indexées, options et cadence du
planificateur, versions des composants et des dépendances principales, SHA-256
des fichiers du moteur/planificateur/contrat, décisions, acquittements,
journaux complets A0/A1 et scores. `comparison_id` est une empreinte du contenu
hors identifiant ; aucun identifiant aléatoire de session n'entre dans le résultat.
Les journaux de vérité sont exposés uniquement pour ces épisodes déjà terminés.

Depuis la racine du dépôt préparé par `demo.py --setup-only` (macOS/Linux) :

```bash
# Produire une comparaison sans ouvrir le cockpit
PYTHONPATH=src:. .venv-demo/bin/python -m hospitalos.simulator.comparison \
  --seed 7 --horizon-minutes 60 --policy accept --output comparaison.json

# Vérifier intégralement un export issu du cockpit ou de la commande précédente
PYTHONPATH=src:. .venv-demo/bin/python -m hospitalos.simulator.comparison \
  --replay comparaison.json --output rejeu.json
```

Le rejeu exige les mêmes empreintes de code et les versions enregistrées de
Python, SimPy, Pydantic, NumPy et scikit-learn, puis vérifie l'égalité complète
du résultat. Une différence est un échec explicite, pas une reproduction déclarée.
Les empreintes ne fournissent pas le code : conserver la révision Git d'origine.
Si le code ou les dépendances changent pendant que le serveur tourne, le
comparateur demande un redémarrage au lieu d'attribuer son résultat au nouveau code.
Les dépendances transitives et le système d'exploitation ne forment pas un
environnement hermétique ; la comparaison complète vérifie le résultat obtenu.

`POST /demo/compare` accepte exclusivement `seed`, `horizon_minutes` et `policy`.
Le calcul est synchrone, limité à une paire à la fois ; une seconde requête
concurrente reçoit HTTP 429. Le client attend au maximum 120 secondes. Un client
déconnecté n'annule pas le calcul borné en cours. Aucun résultat n'est stocké
sur le serveur ; l'export est nécessaire pour le conserver.

## Vérification et limites restantes

`tests/simulator/test_comparison.py` couvre couplage des durées, changement
d'ordre physique, neutralité jusqu'à trois heures, coût du refus, effet négatif,
attentes terminales, rejeu complet, refus de provenance différente, isolation de
la séance interactive, validation des entrées et exclusion concurrente.
`web/src/Comparison.test.tsx` couvre affichage signé/nul, configuration envoyée,
effacement d'un résultat périmé, doublons, erreurs, contrat et export complet.
`python3 demo.py --check` vérifie aussi la neutralité via le proxy du cockpit.

La référence métier reste celle de la petite démo : elle ne remplit pas encore
toutes les exigences métier de M1. Ce lot ne comprend ni campagne multi-régimes,
ni ablation sans world model, ni modèle complet de minutes par rôle,
ni interfaces PAM/FHIR, ni qualification C1–C6/I1/U1. La spécification v0.3
reste inchangée et décrit ces travaux futurs.
