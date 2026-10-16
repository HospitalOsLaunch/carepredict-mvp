# Ressources locales, routage et scénarios appariés — lot 04

GEN-004 ajoute deux organisations au simulateur : services réservés par pôle et
organisation mixte. La capacité hospitalière totale reste identique à chaque heure.
Le changement porte sur les patients autorisés à utiliser ces ressources et sur
les routes d'hébergement/rapatriement.

## Trois mécanismes opérationnels

| Famille | Nettoyage | Imagerie | Transport | Avis | Hébergement |
|---|---|---|---|---|---|
| `v041` | Hôpital | Hôpital | Hôpital | Hôpital | Toutes les unités compatibles, règle historique |
| `local_v1` | Pôle | Pôle | Pôle | Pôle | Dans le pôle d'origine uniquement |
| `hybrid_v1` | Pôle | Hôpital | Pôle | Hôpital | Pôle d'origine d'abord, autres pôles autorisés après un délai |

Les quatre spécialités et les processus cliniques restent hérités de v0.4.1.
Ces familles diffèrent réellement dans l'allocation des ressources ; ce ne sont
pas trois simulateurs cliniques indépendants. Leur existence ne valide pas G4.

Le moteur historique expose désormais quatre points d'extension. Leur comportement
par défaut est comparé au fichier du commit publié `3e9f765` : états, événements,
décisions et tâches doivent être exactement identiques sur la fixture de régression.
Les tests Git nécessitent cet historique ; les workflows récupèrent donc les commits.
L'empreinte des configurations v041 existantes reste inchangée.

## Capacités et files

Les multiplicateurs `shared_resources` dimensionnent toujours le budget global.
Pour chaque service local, ce budget est distribué en créneaux entiers entre pôles,
sans ajout ni duplication de capacité. Les poids par défaut sont les nombres de
lits standard. `pole_resource_weights` permet de multiplier ces poids par service.
Un poids nul réserve zéro capacité à ce pôle ; tous les poids d'un service ne
peuvent pas être nuls. Les poids d'imagerie/avis sont refusés en mode mixte car ces
services restent communs.

L'allocation compense les écarts cumulés aux parts pondérées. Elle est déterministe,
indépendante des patients et ne consomme aucun tirage du moteur. Son calendrier
est calculé depuis le début de la chauffe. Les créneaux inutilisés d'un pôle ne
sont pas prêtés à un autre. La file garde l'ordre de demande au sein de chaque
groupe ; une demande sans capacité locale ne bloque pas les autres groupes.

Le nettoyage mesure des agents simultanément disponibles. Les tâches déjà
engagées se terminent même si le budget baisse ensuite ; aucun nouveau nettoyage
ne démarre au-delà de la capacité libre. L'imagerie et les avis utilisent un budget
de démarrages par heure. Le transport de sortie et les rapatriements consomment
**le même budget**, celui du pôle de départ du patient pour un service local.

Une demande patient en attente relève de son unité actuelle ; elle change de
périmètre après un transfert. Un nettoyage reste attaché au lit concerné.
Les durées de service et le transport instantané au pas horaire restent des
hypothèses héritées. La mutualisation des soignants n'est pas ajoutée.

Les exports locaux/mixtes ajoutent `truth/resource_pools_hourly.csv` :
heure relative, service, portée, identifiant du groupe, capacité, limite de nouveaux
démarrages, démarrages, file et nettoyages actifs. L'hôpital et le monde sont ceux
du manifeste parent ; joindre ces identifiants en réunissant plusieurs exports.
Les capacités et files globales continuent d'être exportées une seule fois dans
`shared_resources_hourly.csv`. Les lignes de groupes ne sont pas de nouvelles
observations « telles que connues » : elles sont de la vérité de simulation.

## Routage dirigé

En mode mixte, `cross_pole_delay_h` vaut 12 heures par défaut, mesurées depuis la
demande d'admission. Le seuil historique minimal d'hébergement continue aussi
de s'appliquer. Les lits du pôle d'origine ont priorité, même si un autre pôle
dispose de davantage de lits. La compatibilité isolement/oxygène reste obligatoire.

`routing_links` décrit des liens orientés entre pôles. Une liste vide signifie
que toutes les routes entre pôles sont permises en mode mixte. Une liste non vide
limite les hébergements et les retours aux directions nommées. Il faut donc nommer
les deux directions pour une liaison bidirectionnelle. Le rapatriement dépend
aussi d'un lit disponible et du transport ; il n'impose pas le délai d'hébergement.
Les familles historique et locale refusent des liens sans effet.

Les orientations hors du périmètre restent possibles selon le mécanisme historique.
Elles sont comptées dans les comparaisons : une file réduite par des patients
orientés ailleurs ne doit pas être présentée seule comme une amélioration.

## Exécuter une organisation

```bash
PYTHONPATH=src python -m hospitalos.synthetic \
  --config configs/synthetic/hospital_local_v1.json \
  --output runs/synthetic/local-year

PYTHONPATH=src python -m hospitalos.synthetic.learning \
  --source runs/synthetic/local-year \
  --output runs/synthetic/local-asof
```

Les exemples `hospital_v041.json`, `hospital_local_v1.json` et
`hospital_hybrid_v1.json` définissent le même hôpital de développement, la même
année et la même graine. Seule l'organisation change. Ils ne font pas partie du
test final réservé.

## Comparaisons contrefactuelles à 72 h

```bash
PYTHONPATH=src python -m hospitalos.synthetic.counterfactual \
  --config configs/synthetic/hospital_v041.json \
  --alternative configs/synthetic/hospital_hybrid_v1.json \
  --at-hour 9 --horizon 72 \
  --output runs/synthetic/paired-72h
```

**Effet mesuré :** remplacer l'organisation au début de l'heure indiquée et la
conserver pendant l'horizon, contre conserver l'organisation de référence.
La politique habituelle continue dans les deux branches et réagit aux états
obtenus. Les deux branches partent d'une copie du même état hospitalier et partagent
les mêmes tableaux d'aléas, y compris ceux de la politique. Les nouveaux patients
admis pendant l'horizon font partie du résultat.

Seuls la famille opérationnelle, les poids des ressources locales et le routage
peuvent différer. Modifier la graine, les lits, les arrivées, la durée, les capacités
globales ou le calendrier est refusé. Un horizon qui dépasse la fin enregistrée
est également refusé ; la partition entière de l'hôpital est conservée.

Les résultats, séparés des variables d'apprentissage, donnent par unité, pôle et
hôpital : patients-heures d'attente aux urgences, lits-heures occupés, minutes de
soins non couvertes, orientations externes et transferts internes entrants.
Les stocks sont intégrés sur les états de fin d'heure de l'intervalle
`[decision_h, decision_h + horizon)`. Les transferts du résultat sont comptés
une fois à leur arrivée : ils mesurent une activité, pas un solde d'admissions.
Le delta vaut toujours **alternative moins référence**.

Ce sont des vérités conditionnelles de simulation pour un état et une graine.
Un changement de famille modifie plusieurs règles ensemble : son effet ne peut
pas être attribué à une seule composante. Le changement est immédiat, sans délai
de redéploiement. Les soins et nettoyages en cours se terminent ; les prochains
démarrages suivent les nouveaux budgets. Ces hypothèses ne sont pas une preuve
d'effet réel ni une recommandation opérationnelle.

Les fichiers `outcomes.csv`, `baseline_config.json`, `alternative_config.json`
et `manifest.json` sont publiés atomiquement dans un nouveau dossier. Le manifeste
déclare l'estimand, les unités, la population, les versions, les empreintes,
les contrôles et l'ouverture éventuelle du test. Pour un export de partition
`test`, un `--test-protocol` explicite est requis, comme pour les cohortes.
L'API de calcul reste une fonction de simulation, pas un contrôle d'accès.

## Réservation par mécanisme

`configs/synthetic/cohort_mechanisms_v1.json` réserve v041 à l'apprentissage,
local_v1 à la validation et hybrid_v1 au test : deux établissements et deux
répétitions par partition, soit 12 mondes. Le lot fige le registre, sans générer
les trajectoires du test.

Le mode `split_axis="mechanism"` autorise des compositions structurelles identiques
dans différentes partitions pour isoler cet axe ; il refuse de partager une
famille opérationnelle. Le mode `structure` conserve les gardes du lot 03.
Les identités hospitalières restent toujours disjointes. Lors de l'union de
registres, appeler `validate_worlds` avec le même axe de découpage.

La définition des familles est connue du développeur. Les essais techniques sur
des hôpitaux `development` vérifient aussi le mode mixte ; ils ne doivent pas être
réutilisés pour entraîner/sélectionner un modèle destiné à une évaluation où cette
famille est tenue à l'écart. Aucun modèle n'est ajusté dans ce lot.

## Vérification et suite

Les [preuves du lot](evidence/lot04_validation.md) détaillent les trois réalisations
annuelles et les comparaisons à 72 h. Les tests couvrent la conservation des
capacités, la concurrence entre pôles, les routes dirigées, le délai, les mutations
de capacité, les limites temporelles, les configurations contrefactuelles et
l'intégration au pipeline d'observation.

Les registres déjà figés restent liés à leurs versions de code et de dépendances ;
les rejouer exige de restaurer celles-ci. La prochaine étape du socle est de
consolider le protocole d'évaluation et les références multi-hôpitaux
(saisonnalité, gradient boosting, puis modèle hybride à règles).
Les variantes d'arrivées, de sortie clinique et d'effectifs restent à diversifier.
