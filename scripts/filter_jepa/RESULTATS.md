# Filtrage, JEPA et décisions — 20 novembre 2026

## Intégration JEPA

Le pilote initial a été reproduit sur la graine 11. Les 30 lignes de métriques sont identiques à celles de l’archive. GraphWM expose ses états latents avec return_latents=True. L’entraînement compare raw, filter et filter_jepa. La compatibilité de la sortie historique et la propagation causale sont testées.

## Correction du filtre

Le prédicteur GraphWM propose une correction des logarithmes des probabilités projetées par le filtre. Le softmax conserve des fractions positives de somme un. L’initialisation nulle de la tête reproduit exactement le filtre. L’objectif JEPA auxiliaire peut être ajouté à la perte supervisée sur les fractions de lits.

Trois paires indépendantes sont utilisées. Graines d’entraînement 101, 103, 107, graines d’évaluation 1001, 1003, 1007. Chaque paire couvre cinq ans et dix tours successifs. Chaque tour utilise cinq mois d’apprentissage puis un mois de projection. Aucun gradient ne vient des trajectoires d’évaluation. Les observations précédant chaque origine sont disponibles. Une projection n’utilise aucune observation future. Le calendrier et les renforts sont connus.

Erreur absolue moyenne, lits prêts par unité, moyenne des 30 mois.

| Variante | MAE |
|---|---|
| Filtre projeté | 1,736790 |
| Correction GraphWM | 1,755817 |
| Correction GraphWM avec JEPA | 1,767114 |

À J+1, les erreurs sont respectivement 1,550170, 1,516540 et 1,514906. À J+7 elles sont 1,806702, 1,832084 et 1,847860. À J+30 elles sont 1,866894, 1,887776 et 1,930113. Ce sont des moyennes descriptives sur trois trajectoires. Le filtre est retenu pour le test décisionnel exploratoire suivant.

Commande depuis la racine du dépôt, avec NumPy et PyTorch disponibles.

```bash
python scripts/filter_jepa/residual.py --out runs/residual
```

## Transfert au simulateur INT-1

Le moteur existant fonctionne à quinze minutes et représente transport, nettoyage, transferts, aval et soins. Le modèle journalier à trois états requiert une adaptation pour ce moteur. Le test utilise un estimateur probabiliste des tâches de nettoyage et de transport encore inachevées, conditionné par l’absence de confirmation et l’âge de la tâche. Les durées de service et les retards de notification sont supposés exponentiels et indépendants. Leurs moyennes sont estimées sur les observations publiques de 12 structures d’entraînement distinctes.

La calibration utilise 459 nettoyages et 266 transports terminés. Le fait de sélectionner les tâches terminées peut biaiser les durées. L’hypothèse exponentielle et ce biais restent à examiner. Cet adaptateur est une nouvelle expérimentation de filtrage et requiert sa propre validation.

Évaluation exploratoire sur 12 structures fragiles à quatre unités, deux futurs appariés, quatre décisions sur 24 heures. Les deux politiques choisissent entre nettoyage et transport dans le premier créneau où les deux renforts sont admissibles, par charge estimée rapportée aux effectifs. Elles utilisent leurs propres observations et les mêmes aléas exogènes. La référence utilise la charge déclarée. La variante probabiliste pondère les tâches en cours par la probabilité qu’elles soient encore inachevées.

Les 24 paires ont exactement les mêmes choix. Moyennes par épisode dans les deux variantes.

| Mesure | Valeur |
|---|---|
| Attente | 13 801,875 patients-minutes |
| Soins non couverts | 4 592,75 minutes |
| Heures-agents engagées | 48 |
| File terminale | 12,333 patients |
| Rupture | 111,25 minutes |

Les heures-agents incluent les engagements différés au-delà de la fin d’évaluation. Le résultat établit l’absence de différence sur ce panel et cette règle. Le gain décisionnel reste à démontrer. L’objectif JEPA a été évalué sur les prévisions de lits seulement.

```bash
python scripts/filter_jepa/decisions.py runs/decisions
python -m unittest discover -s scripts/filter_jepa -p 'test_*.py'
```

Les métriques détaillées sont dans evidence/filter_jepa/residual et evidence/filter_jepa/decisions. Les partitions FILTER_SERVICE_TRAIN et FILTER_DECISION_TEST sont distinctes des partitions INT-1 historiques. Les prochaines évaluations doivent utiliser de nouvelles structures et un plan fixé avant l’observation des résultats.

## Suite proposée

Examiner la calibration des probabilités de tâches inachevées avec censure et retards de déclaration, puis évaluer une sélection d’actions par simulation prospective sur de nouvelles structures. Les cas où les actions possibles ont des conséquences proches méritent une analyse de sensibilité aux retards. Le critère final reste l’attente à budget égal et les soins non couverts.
