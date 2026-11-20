# Validation du filtrage et de la décision

Expérience préclinique entièrement synthétique sur le moteur HospitalOS INT-1 existant. Le protocole est dans protocol.json. L'empreinte consignée avant lancement figure dans evidence/filter_validation/protocol.sha256.

Le filtre estime la probabilité qu'un nettoyage ou un transport publiquement en cours soit encore inachevé. Il modélise séparément durée de service et retard de notification. Les durées de service suivent une loi lognormale arrondie au pas de quinze minutes. Les notifications suivent une loi exponentielle discrétisée. La vraisemblance comprend les fins déclarées et les tâches dont la notification n'est pas arrivée avant la coupure. L'estimation utilise uniquement les événements disponibles avant cette coupure. Les débuts encore invisibles restent exclus de la population d'apprentissage.

Les fractions de tâches inachevées corrigent les comptes de nettoyage et transport. Une fin de nettoyage probable augmente le compte estimé de lits libres. L'estimateur conserve les statuts déclarés pour les autres transitions. Il peut donc surestimer les lits libres lorsqu'un placement intervenu ensuite est encore invisible.

Trois retards moyens sont testés, 0, 60 et 180 minutes. Les 16 structures d'apprentissage et les 8 structures d'évaluation appartiennent à des partitions distinctes. Les mêmes structures sont rejouées sous les trois retards. Les structures ont quatre unités, un régime fragile et des contraintes simultanées de nettoyage et de transport. Aucune sélection selon les résultats n'est appliquée.

La calibration est mesurée chaque heure pendant 24 h. Les probabilités portent sur les services publiquement en cours. Les observations répétées d'une même tâche sont corrélées. Les intervalles sont donc obtenus par rééchantillonnage de structures. Les diagrammes de calibration utilisent dix classes fixes. Les résultats agrégés par tâche peuvent être influencés par le nombre d'observations dans chaque structure.

Les quatre politiques évaluées utilisent un budget commun et les mêmes créneaux admissibles. La règle de charge utilise les comptes déclarés. Les autres politiques comparent les deux renforts par projection dans le moteur INT-1 sur 24 h et trois futurs hypothétiques indépendants des futurs évalués. Elles utilisent respectivement l'état déclaré, des états échantillonnés à partir du filtre et l'état vrai courant. Les paramètres structurels du simulateur sont fournis aux trois planificateurs. Le comparateur à état vrai connaît les états courants et ses durées futures sont retirées puis rééchantillonnées. Ce comparateur fournit un diagnostic de valeur de l'information sous ce planificateur, avec un budget de projection limité.

Les quatre décisions sont espacées de six heures. Seuls nettoyage et transport sont candidats. Les soins non couverts, les patients-minutes d'attente, les files, les rejets et les heures-agents sont lus dans le moteur d'évaluation. Les heures-agents incluent les engagements différés, y compris au-delà des 24 h évaluées.

## Reproduction

Depuis la racine du dépôt, avec Python, NumPy, SciPy, Pandas et PyTorch installés.

```bash
python -m unittest discover -s scripts/filter_validation -p 'test_*.py'
python scripts/filter_validation/campaign.py fit --out evidence/filter_validation/run
for index in 0 1 2 3 4 5 6 7; do
    python scripts/filter_validation/campaign.py evaluate --out evidence/filter_validation/run --index "$index"
done
python scripts/filter_validation/analyse.py evidence/filter_validation/run
```

L'analyse exige les 24 fichiers structure-retard. Chaque fichier contient les deux futurs, les prédictions d'état, les probabilités par tâche, les décisions et les coûts prévus. Les paramètres ajustés sont dans fit.json. La graine du bootstrap et les partitions sont fixées dans le protocole.
