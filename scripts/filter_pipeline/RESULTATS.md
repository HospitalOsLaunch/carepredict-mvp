# Filtrage, conséquences et JEPA — résultats du 20 novembre 2026

**Les trois étapes ont été exécutées. Le filtre étendu améliore certaines estimations d'état ; JEPA apporte un petit gain de prévision des lits libres. Aucun gain opérationnel satisfaisant simultanément les critères d'attente et de soins n'est établi. JEPA reste expérimental.** Statut `PROTOTYPE_UNVALIDATED`, données exclusivement synthétiques.

## 1. Filtrage des événements encore invisibles

Apprentissage sur 16 structures, sélection sur 4 autres et évaluation sur 8 nouvelles structures de quatre unités. Retards moyens de notification de 60 et 180 minutes. Les partitions ne partagent aucune structure.

Les nouvelles composantes infèrent les sorties ordinaires déjà effectuées et les nettoyages/transports déjà commencés. Les sorties éligibles sont certaines dans les règles de ce simulateur ; le cas d'une seule classe est traité explicitement. Les débuts de service utilisent des probabilités apprises sur les données TRAIN. Les fins de transport restent conservatrices, comme dans le correctif précédent.

Erreurs absolues moyennes de comptage par unité et instant, comparées au filtre prudent précédent :

| Retard | Variable | Filtre prudent | Filtre étendu | Gain moyen |
|---|---|---:|---:|---:|
| 60 min | Nettoyages actifs | 0,0924 | 0,0794 | 0,0130 |
| 60 min | Transports actifs | 0,0938 | 0,0742 | 0,0195 |
| 60 min | Lits occupés | 0,0664 | 0,0612 | 0,0052 |
| 180 min | Nettoyages actifs | 0,1335 | 0,1309 | 0,0026 |
| 180 min | Transports actifs | 0,1458 | 0,1276 | 0,0182 |
| 180 min | Lits occupés | 0,1914 | 0,1732 | 0,0182 |

Les lits libres et les files restent identiques au filtre prudent sur ce panel. Le gain sur les transports est positif dans les intervalles bootstrap par structure aux deux retards. Le gain sur le nettoyage reste incertain ; celui sur l'occupation à 180 minutes a un intervalle [0,0026 ; 0,0339]. Cette extension ne constitue pas une inférence complète de toutes les arrivées, sorties et tâches invisibles.

## 2. Prévisions des conséquences à 6, 12 et 24 heures

Huit autres structures sont évaluées. Les projections comparent l'abstention et deux renforts, avec des futurs indépendants des futurs évalués. L'erreur de trajectoire est distincte de l'erreur de l'effet d'une action contre l'abstention.

Exemple à 180 minutes de retard, sur l'attente cumulée en patients-minutes :

| Horizon | Erreur de trajectoire, prudent | Erreur de trajectoire, étendu | Erreur d'effet, prudent | Erreur d'effet, étendu |
|---|---:|---:|---:|---:|
| 6 h | 685,4 | 702,3 | 4,4 | 5,0 |
| 12 h | 1 437,4 | 1 489,7 | 42,6 | 44,5 |
| 24 h | 4 006,9 | 3 875,8 | 133,6 | 136,6 |

Le filtre étendu améliore légèrement la trajectoire à 24 h dans cet exemple, mais dégrade d'autres métriques. Les décisions à 24 h restent équivalentes entre état public, filtre prudent et filtre étendu. Leur regret moyen est de 0,94 patient-minute face au meilleur coût moyen parmi les actions sur les deux futurs évalués. Le comparateur à état vrai atteint un regret nul sur ce petit panel, avec 14 heures-agents en moyenne contre 12 pour les autres. Ce panel offre donc très peu de marge décisionnelle ; il ne démontre pas un gain opérationnel du filtrage.

## 3. Entraînement avec et sans JEPA

Le corpus vérifié contient **360 épisodes mensuels et 43 848 transitions de six heures**. Chaque structure couvre janvier 2020 à décembre 2024, avec 60 épisodes mensuels et sept jours de mise en régime par épisode. Trois structures servent à l'apprentissage et trois autres à l'évaluation. Les mois sont réinitialisés : ce n'est pas une trajectoire continue de cinq ans.

Les variantes physique seule et physique + JEPA utilisent trois graines, dix cycles chronologiques par graine, cinq mois d'apprentissage puis le sixième mois prédit sans nouvelles observations, et 80 mises à jour par cycle. Les poids sont conservés entre cycles. Les six modèles finaux et les états de leurs optimiseurs sont sauvegardés.

Deux corrections ont été faites avant l'entraînement final : aligner les créneaux des tests d'actions sur ceux vus à l'apprentissage, et permettre aux messages des ressources d'affecter les unités dans le même intervalle. La deuxième correction est une option de GraphWM activée dans les deux variantes ; le comportement par défaut des anciens modèles est conservé bit à bit.

### Prévision mensuelle

| Métrique | Physique seule | Physique + JEPA |
|---|---:|---:|
| Erreur sur les lits libres, lits/unité | 0,518 | **0,486** |
| Erreur sur les files, patients/unité | 10,909 | 10,928 |
| Erreur moyenne des neuf variables d'état, en comptes | 4,034 | 4,032 |
| Erreur absolue de l'attente mensuelle, patients-minutes | 1 500 373 | 1 487 279 |
| Erreur absolue des soins non couverts mensuels, minutes | 74 415 | 75 673 |

Le gain sur les lits libres est de **6,0 %**, soit 0,031 lit par unité en moyenne. Il est positif sur les trois graines. L'intervalle exploratoire rééchantillonnant graines et structures est [0,021 ; 0,041] lit. Il n'y a que trois structures TEST indépendantes : cela limite fortement la portée de cet intervalle.

La référence de persistance atteint 1,131 lit d'erreur et la moyenne des mois TRAIN 0,597. Le modèle JEPA figé après le premier cycle atteint 0,818 sur les mêmes mois évalués, contre 0,486 pour le modèle poursuivant l'entraînement. Les cycles supplémentaires apportent donc un gain physique par rapport à cette référence figée.

Les autres gains ne sont pas établis. L'erreur absolue mensuelle d'attente reste de l'ordre de **44 %** du volume moyen réel synthétique, et celle des soins non couverts de l'ordre de **35 %**. Le modèle n'est pas suffisamment précis sur ces agrégats pour revendiquer une capacité opérationnelle complète.

### Le « gap » ne diminue pas automatiquement à chaque cycle

La perte latente JEPA mesurée sur le test vaut en moyenne 0,397 au premier cycle et 0,411 au dixième. Elle ne présente donc pas de baisse monotone démontrée. Les mois évalués et l'encodeur cible EMA changent entre cycles ; les métriques physiques et la référence figée sont plus interprétables pour mesurer le progrès. La variance de la cible reste non nulle, sans que ce seul diagnostic suffise à caractériser toute la représentation.

La tête de prédiction latente du témoin sans JEPA n'est pas entraînée. Comparer directement son erreur latente à celle de JEPA ne prouverait pas un bénéfice du world model.

### Choix d'actions à 24 heures

Avec abstention possible, même plafond de budget :

| Résultat moyen | Physique seule | Physique + JEPA |
|---|---:|---:|
| Attente, patients-minutes | 33 939,3 | 33 956,6 |
| Regret, patients-minutes | 79,6 | 96,8 |
| Soins non couverts, minutes | 6 598,6 | 6 610,2 |
| Heures-agents engagées | 12,27 | 5,87 |

JEPA est plus économe en renforts mais augmente l'attente de 17,25 patients-minutes en moyenne. Deux graines dégradent ce résultat et une l'améliore. L'intervalle croisé du gain d'attente est [−72,25 ; 42,5] : aucun gain n'est établi.

Un diagnostic complémentaire impose la même dépense de 16 heures-agents en comparant uniquement nettoyage et transport. JEPA réduit alors l'attente moyenne de 27,67 patients-minutes, mais augmente les soins non couverts de 19,03 minutes. Ce diagnostic ne satisfait pas non plus le critère commun d'amélioration sans dégradation des soins. Il n'est pas une nouvelle politique validée.

## Vérifications et livraison

- **22 tests ciblés passent** : 8 nouveaux, 10 de filtrage/reconstruction et 4 existants du filtre quotidien et de l'interface JEPA.
- Contrôle d'identité bit à bit du GraphWM par défaut contre le commit parent sur trois graines.
- Rechargement des six checkpoints : leurs prévisions reproduisent exactement les prévisions sauvegardées du dernier mois évalué.
- Empreintes des protocoles actifs, du corpus et des sources contrôlées ; données et résultats négatifs conservés.
- Aucune exécution complète de la CI du dépôt ni validation sur des données hospitalières réelles n'est revendiquée.

Les commandes et limites de reproduction sont dans [README.md](README.md). Les artefacts sont référencés dans [artifacts.json](../../evidence/filter_pipeline/artifacts.json) et le manifeste SHA-256 dans [artifacts_manifest.json](../../evidence/filter_pipeline/artifacts_manifest.json). Décompresser l'archive dans `evidence/filter_pipeline` restitue les données et checkpoints attendus par les scripts.

## Décision pour la suite

Conserver les correctifs de causalité et l'extension du filtre pour les expériences. Conserver JEPA comme variante de recherche. La prochaine priorité est l'apprentissage apparié des **effets d'action**, avec un objectif et un planificateur qui prennent explicitement en compte les soins non couverts. Réduire uniquement l'erreur de lits libres ou la perte latente ne suffit pas à choisir de meilleures actions.
