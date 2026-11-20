# Filtrage, conséquences et JEPA — campagne séquentielle

Cette campagne exécute trois étapes dans l'ordre. Elle est entièrement synthétique et conserve le statut `PROTOTYPE_UNVALIDATED`.

## 1. Événements encore invisibles

Le filtre prudent précédent est étendu avec trois événements candidats : sortie ordinaire déjà effectuée, nettoyage déjà commencé, transport déjà commencé. Les covariables sont exclusivement publiques : statut, ancienneté connue, heure, files et capacités déclarées. Les vérités du simulateur sont utilisées comme étiquettes uniquement sur les structures TRAIN.

Les sorties ordinaires éligibles sont déterminées par les règles du moteur : patient prêt, sans transfert interne ni attente aval, sans transport restant. Lorsque l'apprentissage ne contient qu'une classe, une probabilité constante remplace le classifieur. Les débuts de service utilisent un classifieur à gradient boosting. Ce sont des estimations conditionnelles sur les candidats visibles, pas un filtre bayésien complet de tous les événements hospitaliers.

Les seize structures TRAIN, quatre DEV et huit TEST appartiennent à des partitions distinctes. Les composantes sont sélectionnées sur DEV selon le Brier puis le gain agrégé sur les comptes. Le choix est figé avant TEST. Les particules respectent les lits, les identités, l'isolement et la capacité disponible des services. L'inférence des fins de transport reste désactivée.

## 2. Conséquences des actions

Huit autres structures, deux retards de notification, deux futurs réels synthétiques appariés et trois futurs prospectifs indépendants. Les actions sont l'abstention, le renfort de nettoyage ou celui de transport sur le même créneau. Les quatre initialisations sont l'état public, le filtre prudent, le filtre étendu et l'état vrai courant.

Les résultats mesurent à 6/12/24 h les lits libres, les files, l'attente cumulée et les soins non couverts. Ils distinguent erreur de trajectoire, erreur sur l'effet de l'action contre abstention et regret de la décision. Ce regret utilise le meilleur coût moyen parmi les actions sur deux futurs d'évaluation ; c'est un comparateur rétrospectif bruité, pas une borne optimale exacte.

Tous les simulateurs prospectifs connaissent les mêmes paramètres structurels. Seul le comparateur d'état vrai connaît l'état courant réel. Aucun ne reçoit les innovations futures effectivement évaluées. Le benchmark porte sur une décision, pas une politique hospitalière complète.

## 3. Cinq années calendaires, dix cycles

Le corpus contient 60 épisodes mensuels par structure entre janvier 2020 et décembre 2024. Il comporte trois structures TRAIN et trois TEST, toutes distinctes des partitions précédentes. Chaque mois est réinitialisé et précédé de sept jours de mise en régime. Il ne s'agit donc pas d'une trajectoire hospitalière continue sur cinq ans. Les transitions à travers les réinitialisations sont exclues.

Les cinq premiers mois de chaque semestre entraînent le modèle ; le sixième est prédit depuis son origine sans observation intermédiaire. Les poids sont conservés entre les dix semestres. Les mois de test ne sélectionnent aucun hyperparamètre. Les trois graines de modèles sont 11, 23 et 37.

Le moteur est INT-1 à quatre unités, avec patients, lits, transferts, aval, nettoyage, transport et charge de soins. L'adaptateur de recherche utilise un sous-ensemble structuré normalisé dans les 54 entrées de GraphWM, des ressources et des liens entre unités ; il ne reprend pas toutes les variables historiques de l'adaptateur de production. Les plans quotidiens de renfort sont exogènes, connus à l'origine de la prévision. Les scénarios ne modélisent pas tous les services d'un hôpital réel.

Les modèles partagent la même initialisation, les mêmes minibatches, 80 mises à jour par cycle, une largeur de 24 et les mêmes pertes physiques. JEPA ajoute une prédiction latente vers un encodeur cible EMA sans gradient, une normalisation et un terme contre l'effondrement de variance. Le budget de mises à jour est identique, pas nécessairement le coût de calcul. La tête latente du témoin sans JEPA n'est pas entraînée : son erreur latente ne sert pas à démontrer un gain contre le témoin. Les métriques physiques et décisionnelles sont prioritaires.

Un modèle figé au premier cycle est réévalué sur les mêmes mois pour mesurer le gain des cycles ultérieurs. La persistance et une moyenne calculée uniquement sur les mois TRAIN servent également de références.

### Deux corrections de conception avant l'entraînement final

- Le test contrefactuel utilise désormais le créneau 06–14 h vu à l'apprentissage. Son origine est minuit au début du mois, avec effets nuls avant 6 h. Les anciens tests à 14–22 h introduisaient un créneau absent de l'apprentissage. Seuls les tableaux de ces tests ont été régénérés ; les trajectoires mensuelles restent inchangées.
- L'option `GraphWM(..., instant_resource_messages=True)` transmet l'effet du plan de ressources dans l'intervalle courant, au lieu d'un intervalle plus tard. Elle est identique dans les deux variantes. Sa valeur par défaut reste `False` pour les anciens modèles ; l'identité bit à bit avec le code parent a été contrôlée sur trois graines.

Les tableaux contrefactuels testent, à l'origine du mois, l'abstention et les deux renforts avec deux futurs appariés. Ils mesurent les prévisions et le choix à 6/12/24 h, sur trois structures et dix mois de test. Les intervalles par structure sont exploratoires avec seulement trois établissements indépendants.

## Reproduction

Depuis la racine du dépôt, avec Python, PyTorch CPU, NumPy, SciPy, Pandas et scikit-learn. Les processus indépendants au sein de la génération ou des graines peuvent être exécutés simultanément ; les trois étapes restent séquentielles.

```bash
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
python -m unittest discover -s scripts/filter_pipeline -p 'test_*.py'
python scripts/filter_pipeline/filter_stage.py fit
python scripts/filter_pipeline/filter_stage.py select
python scripts/filter_pipeline/filter_stage.py test
python scripts/filter_pipeline/consequences.py
python scripts/filter_pipeline/analyse_pipeline.py base
python scripts/filter_pipeline/build_corpus.py
python scripts/filter_pipeline/train_all.py
python scripts/filter_pipeline/analyse_pipeline.py jepa
```

La génération actuelle produit directement les tests d'actions corrigés. `rebuild_probes.py` documente la correction des premiers fichiers produits pendant cette campagne et permet de mettre à jour ces anciennes données.

Les paramètres sont dans `protocol.json`. Les empreintes actives sont `filter_test_frozen.sha256`, `consequence_frozen.sha256` et `jepa_frozen.sha256`. Les empreintes contenant `draft` gardent la trace des versions antérieures de conception. Les données, poids, prédictions détaillées et états des optimiseurs sont fournis dans l'archive de résultats. Les synthèses et le manifeste sont dans `evidence/filter_pipeline`.
